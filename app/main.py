from fastapi import FastAPI, Depends, HTTPException, status, Query, WebSocket, WebSocketDisconnect, UploadFile, File
from sqlalchemy.orm import Session
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import random
import logging
import httpx
import json
import os
from datetime import datetime, timedelta
from . import models, schemas, ai_service, auth_utils, auth_router
from .pytorch_vision_engine import vision_engine
from .database import engine, get_db
from .websocket_manager import manager as ws_manager
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)

# Create tables and sync schema non-blockingly
def _init_db_schema():
    try:
        models.Base.metadata.create_all(bind=engine)
        import sync_db
        sync_db.sync_db(bind_engine=engine)
        logging.getLogger("uvicorn.error").info("[Startup] Database tables synchronized.")
    except Exception as sync_err:
        logging.getLogger("uvicorn.error").warning(f"[Startup DB Sync Warning] {sync_err}")

import threading
threading.Thread(target=_init_db_schema, daemon=True).start()

logger_startup = logging.getLogger("uvicorn.error")

ENV = os.getenv("ENV", "production")
show_docs = os.getenv("SHOW_DOCS", "false").lower() in ("true", "1", "yes") or ENV == "development"

app = FastAPI(
    title="AgriNex AI Enterprise Backend",
    docs_url="/docs" if show_docs else None,
    redoc_url="/redoc" if show_docs else None,
)

# CORS configuration
allowed_origins_str = os.getenv("ALLOWED_ORIGINS", "")
default_origins = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://localhost:8000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
    "https://agrinex-web.vercel.app",
    "https://agrinex-ai.vercel.app",
    "https://agrinex-backend-c1ig.onrender.com",
]

if allowed_origins_str:
    env_origins = [origin.strip() for origin in allowed_origins_str.split(",") if origin.strip()]
    allow_origins = list(set(default_origins + env_origins))
else:
    allow_origins = default_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)

logger = logging.getLogger("uvicorn.error")
logger.info("[Startup] Application ready. Brevo Transactional Email API will be used on-demand during OTP requests.")

@app.on_event("startup")
async def startup_event():
    logger.info("[Startup] AgriNex AI Enterprise Backend starting...")
    import asyncio
    from .pytorch_vision_engine import vision_engine
    asyncio.create_task(asyncio.to_thread(vision_engine.load_model))

@app.middleware("http")
async def log_requests(request, call_next):
    logger.info(f"Incoming request: {request.method} {request.url.path}")
    response = await call_next(request)
    logger.info(f"Response status: {response.status_code}")
    return response

# ─── Auth (JWT Implementation) ───
def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    if not token:
        logger.warning("Unauthenticated access attempt")
        raise credentials_exception
    try:
        payload = jwt.decode(token, auth_utils.SECRET_KEY, algorithms=[auth_utils.ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    user = db.query(models.User).filter(models.User.email == email).first()
    if user is None:
        raise credentials_exception
    return user

def get_optional_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> Optional[models.User]:
    if not token:
        return None
    try:
        payload = jwt.decode(token, auth_utils.SECRET_KEY, algorithms=[auth_utils.ALGORITHM])
        email: str = payload.get("sub")
        if email:
            return db.query(models.User).filter(models.User.email == email).first()
    except Exception:
        pass
    return None

@app.get("/")
def read_root():
    return {"message": "AgriNex AI Backend is Live"}

@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    try:
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        return {"status": "error", "database": str(e)}

# ─── User Profile ───
@app.get("/auth/me", response_model=schemas.UserOut)
def get_me(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    followers_count = db.query(models.Follow).filter(models.Follow.following_id == current_user.id).count()
    following_count = db.query(models.Follow).filter(models.Follow.follower_id == current_user.id).count()
    posts_count = db.query(models.Post).filter(models.Post.user_id == current_user.id).count()
    
    user_out = schemas.UserOut.from_orm(current_user)
    user_out.followers_count = followers_count
    user_out.following_count = following_count
    user_out.posts_count = posts_count
    return user_out

@app.put("/user/profile", response_model=schemas.UserOut)
@app.patch("/user/profile", response_model=schemas.UserOut)
@app.put("/api/user/profile", response_model=schemas.UserOut)
@app.patch("/api/user/profile", response_model=schemas.UserOut)
@app.put("/users/profile", response_model=schemas.UserOut)
@app.patch("/users/profile", response_model=schemas.UserOut)
@app.put("/api/users/profile", response_model=schemas.UserOut)
@app.patch("/api/users/profile", response_model=schemas.UserOut)
@app.put("/users/me", response_model=schemas.UserOut)
@app.patch("/users/me", response_model=schemas.UserOut)
@app.put("/api/users/me", response_model=schemas.UserOut)
@app.patch("/api/users/me", response_model=schemas.UserOut)
def update_profile(user_update: schemas.UserUpdate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Username uniqueness validation
    if user_update.username:
        clean_username = user_update.username.strip().lstrip('@')
        if clean_username:
            existing = db.query(models.User).filter(
                models.User.username.ilike(clean_username),
                models.User.id != current_user.id
            ).first()
            if existing:
                raise HTTPException(status_code=400, detail="Username already exists. Please choose a different username.")
            user_update.username = clean_username

    if user_update.bio and len(user_update.bio.strip()) > 250:
        raise HTTPException(status_code=400, detail="Bio cannot exceed 250 characters.")

    for key, value in user_update.dict(exclude_unset=True).items():
        if value is not None and isinstance(value, str):
            value = value.strip()
        setattr(current_user, key, value)

    try:
        db.commit()
        db.refresh(current_user)
    except Exception as e:
        db.rollback()
        logger.error(f"[Profile Update Error] {e}")
        raise HTTPException(status_code=500, detail="Database update failed. Please try again.")
    
    return prepare_user_out(current_user, current_user.id, db)


def prepare_user_out(user_obj: models.User, current_user_id: Optional[int], db: Session) -> schemas.UserOut:
    followers_count = db.query(models.Follow).filter(models.Follow.following_id == user_obj.id).count()
    following_count = db.query(models.Follow).filter(models.Follow.follower_id == user_obj.id).count()
    posts_count = db.query(models.Post).filter(models.Post.user_id == user_obj.id).count()
    
    is_following = False
    if current_user_id and current_user_id != user_obj.id:
        is_following = db.query(models.Follow).filter(
            models.Follow.follower_id == current_user_id,
            models.Follow.following_id == user_obj.id
        ).first() is not None

    user_out = schemas.UserOut.from_orm(user_obj)
    user_out.display_name = user_obj.full_name or f"Farmer {user_obj.id}"
    user_out.specialization = user_obj.crop_specialization or "Agriculture Specialist"
    user_out.joined_date = user_obj.created_at
    user_out.profile_photo = user_obj.profile_picture
    user_out.followers_count = followers_count
    user_out.following_count = following_count
    user_out.posts_count = posts_count
    user_out.is_following = is_following
    user_out.isFollowing = is_following
    return user_out

@app.delete("/user")
def delete_account(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(current_user)
    db.commit()
    return {"message": "Account deleted successfully"}

# ─── Static User Routes (search & suggested MUST be before dynamic {user_id}) ───
@app.get("/users/search", response_model=List[schemas.UserSearchOut])
@app.get("/api/users/search", response_model=List[schemas.UserSearchOut])
@app.get("/social/search", response_model=List[schemas.UserSearchOut])
def search_users(
    q: str = Query(..., min_length=1),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: Optional[models.User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db)
):
    from sqlalchemy import or_
    search_term = f"%{q}%"
    current_id = current_user.id if current_user else None

    query = db.query(models.User).filter(
        or_(
            models.User.full_name.ilike(search_term),
            models.User.username.ilike(search_term),
            models.User.email.ilike(search_term),
            models.User.village.ilike(search_term),
            models.User.district.ilike(search_term),
        )
    )
    if current_id:
        blocked_uids = get_blocked_user_ids(db, current_id)
        exclude_uids = blocked_uids | {current_id}
        query = query.filter(~models.User.id.in_(exclude_uids))

    users = query.offset(skip).limit(limit).all()

    results = []
    for u in users:
        is_following = False
        if current_id:
            is_following = db.query(models.Follow).filter(
                models.Follow.follower_id == current_id,
                models.Follow.following_id == u.id
            ).first() is not None
        
        followers_cnt = db.query(models.Follow).filter(models.Follow.following_id == u.id).count()
        following_cnt = db.query(models.Follow).filter(models.Follow.follower_id == u.id).count()

        results.append(schemas.UserSearchOut(
            id=u.id,
            full_name=u.full_name,
            display_name=u.full_name or f"Farmer {u.id}",
            username=u.username,
            email=u.email,
            village=u.village or "Agricultural Hub",
            profile_picture=u.profile_picture,
            profile_photo=u.profile_picture,
            bio=u.bio,
            verified=u.is_verified,
            is_verified=u.is_verified,
            followers=followers_cnt,
            followers_count=followers_cnt,
            following_count=following_cnt,
            is_following=is_following,
            isFollowing=is_following,
        ))
    return results

@app.get("/users/suggested", response_model=List[schemas.UserSearchOut])
@app.get("/api/users/suggested", response_model=List[schemas.UserSearchOut])
def get_suggested_users(
    limit: int = Query(default=5, ge=1, le=20),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    following_ids = [f.following_id for f in db.query(models.Follow.following_id).filter(models.Follow.follower_id == current_user.id).all()]
    blocked_ids = get_blocked_user_ids(db, current_user.id)
    exclude_ids = set(following_ids) | blocked_ids | {current_user.id}

    query = db.query(models.User).filter(~models.User.id.in_(exclude_ids))

    
    suggested = []
    if current_user.crop_specialization or current_user.village:
        from sqlalchemy import or_
        matches = query.filter(
            or_(
                models.User.crop_specialization == current_user.crop_specialization,
                models.User.village == current_user.village
            )
        ).limit(limit).all()
        suggested.extend(matches)

    if len(suggested) < limit:
        already_picked = {u.id for u in suggested}
        already_picked.update(exclude_ids)
        remains = db.query(models.User).filter(~models.User.id.in_(already_picked)).limit(limit - len(suggested)).all()
        suggested.extend(remains)

    res = []
    for u in suggested:
        followers_cnt = db.query(models.Follow).filter(models.Follow.following_id == u.id).count()
        res.append(schemas.UserSearchOut(
            id=u.id,
            full_name=u.full_name,
            display_name=u.full_name or f"Farmer {u.id}",
            username=u.username,
            email=u.email,
            village=u.village or "Agricultural Hub",
            profile_picture=u.profile_picture,
            profile_photo=u.profile_picture,
            bio=u.bio,
            verified=u.is_verified,
            is_verified=u.is_verified,
            followers=followers_cnt,
            followers_count=followers_cnt,
            following_count=0,
            is_following=False,
            isFollowing=False
        ))
    return res

# ─── Dynamic User Routes ───
@app.get("/users/{user_id}", response_model=schemas.UserOut)
@app.get("/api/users/{user_id}", response_model=schemas.UserOut)
def get_user_profile(user_id: int, current_user: Optional[models.User] = Depends(get_optional_current_user), db: Session = Depends(get_db)):
    target_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    current_id = current_user.id if current_user else None
    return prepare_user_out(target_user, current_id, db)

@app.post("/users/{user_id}/follow", response_model=schemas.FollowOut)
@app.post("/api/users/{user_id}/follow", response_model=schemas.FollowOut)
@app.post("/social/follow/{user_id}", response_model=schemas.FollowOut)
def follow_user(user_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot follow yourself")

    target_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    follow = db.query(models.Follow).filter(
        models.Follow.follower_id == current_user.id,
        models.Follow.following_id == user_id
    ).first()

    if not follow:
        new_follow = models.Follow(follower_id=current_user.id, following_id=user_id)
        db.add(new_follow)
        db.commit()
        actor_name = current_user.full_name or f"Farmer {current_user.id}"
        create_notification(db, user_id, current_user.id, "FOLLOW", f"{actor_name} started following you")

    followers_count = db.query(models.Follow).filter(models.Follow.following_id == user_id).count()
    following_count = db.query(models.Follow).filter(models.Follow.follower_id == current_user.id).count()
    return schemas.FollowOut(
        following=True,
        isFollowing=True,
        is_following=True,
        followersCount=followers_count,
        followers_count=followers_count,
        followingCount=following_count,
        following_count=following_count
    )

@app.delete("/users/{user_id}/follow", response_model=schemas.FollowOut)
@app.delete("/api/users/{user_id}/follow", response_model=schemas.FollowOut)
@app.delete("/social/follow/{user_id}", response_model=schemas.FollowOut)
def unfollow_user(user_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot unfollow yourself")

    target_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    follow = db.query(models.Follow).filter(
        models.Follow.follower_id == current_user.id,
        models.Follow.following_id == user_id
    ).first()

    if follow:
        db.delete(follow)
        db.commit()
        actor_name = current_user.full_name or f"Farmer {current_user.id}"
        create_notification(db, user_id, current_user.id, "UNFOLLOW", f"{actor_name} unfollowed you")

    followers_count = db.query(models.Follow).filter(models.Follow.following_id == user_id).count()
    following_count = db.query(models.Follow).filter(models.Follow.follower_id == current_user.id).count()
    return schemas.FollowOut(
        following=False,
        isFollowing=False,
        is_following=False,
        followersCount=followers_count,
        followers_count=followers_count,
        followingCount=following_count,
        following_count=following_count
    )

# ─── Notification Helper ───
def create_notification(db, user_id: int, actor_id: int, notif_type: str, message: str, post_id: int = None):
    """Create a notification. Only sends to the recipient (user_id), never to the actor."""
    if user_id == actor_id:
        return  # Never notify yourself
    try:
        notif = models.Notification(
            user_id=user_id,
            actor_id=actor_id,
            type=notif_type,
            post_id=post_id,
            message=message,
            is_read=False,
        )
        db.add(notif)
        db.commit()
    except Exception as e:
        logger.error(f"[Notification] Failed to create notification: {e}")
        db.rollback()

# ─── Community Posts ───
@app.post("/posts", response_model=schemas.PostOut)
def create_post(post: schemas.PostCreate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        logger.info(f"[CreatePost] User {current_user.id} creating post")
        post_dict = post.dict()
        images_list = post_dict.pop("images", None)

        # Validate content
        if not post_dict.get("content", "").strip():
            raise HTTPException(status_code=400, detail="Post content cannot be empty")

        # Serialize images list to JSON string
        images_json = json.dumps(images_list) if images_list is not None else None

        # Set image_url to first image for backward compatibility
        if not post_dict.get("image_url") and images_list:
            post_dict["image_url"] = images_list[0]

        db_post = models.Post(**post_dict, images=images_json, user_id=current_user.id)
        db.add(db_post)
        db.commit()
        db.refresh(db_post)
        logger.info(f"[CreatePost] Post {db_post.id} created successfully for user {current_user.id}")
        # Pass current_user directly to avoid DetachedInstanceError on lazy-loaded relationship
        return prepare_post_out(db_post, current_user.id, db, author=current_user)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[CreatePost] Error creating post for user {current_user.id}: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create post: {str(e)}")

@app.get("/posts/feed", response_model=List[schemas.PostOut])
@app.get("/posts", response_model=List[schemas.PostOut])
@app.get("/api/posts", response_model=List[schemas.PostOut])
def get_feed(skip: int = 0, limit: int = 20, current_user: Optional[models.User] = Depends(get_optional_current_user), db: Session = Depends(get_db)):
    current_id = current_user.id if current_user else None
    if current_id:
        following_ids = [f.following_id for f in db.query(models.Follow.following_id).filter(models.Follow.follower_id == current_id).all()]
        if following_ids:
            followed_posts = db.query(models.Post).filter(models.Post.user_id.in_(following_ids + [current_id])).order_by(models.Post.created_at.desc()).all()
            other_posts = db.query(models.Post).filter(~models.Post.user_id.in_(following_ids + [current_id])).order_by(models.Post.created_at.desc()).all()
            all_posts = followed_posts + other_posts
            posts = all_posts[skip:skip+limit]
        else:
            posts = db.query(models.Post).order_by(models.Post.created_at.desc()).offset(skip).limit(limit).all()
    else:
        posts = db.query(models.Post).order_by(models.Post.created_at.desc()).offset(skip).limit(limit).all()

    return [prepare_post_out(p, current_id or 0, db) for p in posts]

@app.get("/posts/user/{user_id}", response_model=List[schemas.PostOut])
def get_user_posts_by_alias(
    user_id: int,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, le=100),
    current_user: Optional[models.User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db)
):
    current_id = current_user.id if current_user else user_id
    posts = db.query(models.Post).filter(models.Post.user_id == user_id).order_by(models.Post.created_at.desc()).offset(skip).limit(limit).all()
    return [prepare_post_out(p, current_id, db) for p in posts]

@app.put("/posts/{post_id}", response_model=schemas.PostOut)
def update_post(post_id: int, post_update: schemas.PostUpdate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    post = db.query(models.Post).filter(models.Post.id == post_id, models.Post.user_id == current_user.id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found or unauthorized")
        
    post_dict = post_update.dict(exclude_unset=True)
    if "images" in post_dict:
        images_list = post_dict.pop("images")
        post.images = json.dumps(images_list) if images_list is not None else None
        if images_list and not post_dict.get("image_url"):
            post.image_url = images_list[0]
            
    for key, value in post_dict.items():
        setattr(post, key, value)
        
    db.commit()
    db.refresh(post)
    return prepare_post_out(post, current_user.id, db)

@app.delete("/posts/{post_id}")
def delete_post(post_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    post = db.query(models.Post).filter(models.Post.id == post_id, models.Post.user_id == current_user.id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found or unauthorized")
    db.delete(post)
    db.commit()
    return {"message": "Post deleted successfully"}

def prepare_post_out(post, current_user_id, db, author=None):
    likes_count = db.query(models.Like).filter(models.Like.post_id == post.id).count()
    comments_count = db.query(models.Comment).filter(models.Comment.post_id == post.id).count()
    is_liked = db.query(models.Like).filter(models.Like.post_id == post.id, models.Like.user_id == current_user_id).first() is not None
    is_saved = db.query(models.SavedPost).filter(models.SavedPost.post_id == post.id, models.SavedPost.user_id == current_user_id).first() is not None

    post_out = schemas.PostOut.from_orm(post)
    post_out.likes_count = likes_count
    post_out.comments_count = comments_count
    post_out.is_liked = is_liked
    post_out.is_saved = is_saved

    # Use passed author to avoid DetachedInstanceError after commit
    if author is not None:
        post_out.author_name = author.full_name or f"Farmer {author.id}"
        post_out.author_avatar = author.profile_picture
        post_out.author_verified = author.is_verified
    else:
        try:
            post_out.author_name = post.user.full_name or f"Farmer {post.user.id}"
            post_out.author_avatar = post.user.profile_picture
            post_out.author_verified = post.user.is_verified
        except Exception:
            # Fallback: fetch user manually if lazy-load fails
            u = db.query(models.User).filter(models.User.id == post.user_id).first()
            post_out.author_name = u.full_name if u else f"Farmer {post.user_id}"
            post_out.author_avatar = u.profile_picture if u else None
            post_out.author_verified = u.is_verified if u else False

    # Deserialize images
    if post.images:
        try:
            post_out.images = json.loads(post.images)
        except Exception:
            post_out.images = []
    else:
        post_out.images = [post.image_url] if post.image_url else []

    return post_out

# ─── Likes & Comments ───
@app.post("/posts/{post_id}/like")
def like_post(post_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    like = db.query(models.Like).filter(models.Like.post_id == post_id, models.Like.user_id == current_user.id).first()
    if like:
        db.delete(like)
        db.commit()
        liked = False
    else:
        new_like = models.Like(post_id=post_id, user_id=current_user.id)
        db.add(new_like)
        db.commit()
        liked = True
        # Notify post owner
        post = db.query(models.Post).filter(models.Post.id == post_id).first()
        if post:
            actor_name = current_user.full_name or f"Farmer {current_user.id}"
            create_notification(db, post.user_id, current_user.id, "LIKE",
                f"{actor_name} liked your post", post_id=post_id)
    likes_count = db.query(models.Like).filter(models.Like.post_id == post_id).count()
    return {"liked": liked, "likes_count": likes_count}

@app.delete("/posts/{post_id}/like")
def unlike_post(post_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    like = db.query(models.Like).filter(models.Like.post_id == post_id, models.Like.user_id == current_user.id).first()
    if like:
        db.delete(like)
        db.commit()
    likes_count = db.query(models.Like).filter(models.Like.post_id == post_id).count()
    return {"liked": False, "likes_count": likes_count}

@app.post("/posts/{post_id}/comments", response_model=schemas.CommentOut)
def comment_post(post_id: int, comment: schemas.CommentCreate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    db_comment = models.Comment(post_id=post_id, user_id=current_user.id, content=comment.content, parent_id=comment.parent_id)
    db.add(db_comment)
    db.commit()
    db.refresh(db_comment)
    # Notify post owner
    post = db.query(models.Post).filter(models.Post.id == post_id).first()
    if post:
        actor_name = current_user.full_name or f"Farmer {current_user.id}"
        create_notification(db, post.user_id, current_user.id, "COMMENT",
            f"{actor_name} commented on your post", post_id=post_id)
    out = schemas.CommentOut.from_orm(db_comment)
    out.author_name = current_user.full_name or f"Farmer {current_user.id}"
    out.author_avatar = current_user.profile_picture
    return out

@app.get("/posts/{post_id}/comments", response_model=List[schemas.CommentOut])
def get_comments(post_id: int, db: Session = Depends(get_db)):
    comments = db.query(models.Comment).filter(models.Comment.post_id == post_id, models.Comment.parent_id == None).order_by(models.Comment.created_at.desc()).all()
    res = []
    for c in comments:
        out = schemas.CommentOut.from_orm(c)
        out.author_name = c.user.full_name or f"Farmer {c.user_id}"
        out.author_avatar = c.user.profile_picture
        res.append(out)
    return res

@app.post("/posts/{post_id}/save")
def save_post(post_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    saved = db.query(models.SavedPost).filter(models.SavedPost.post_id == post_id, models.SavedPost.user_id == current_user.id).first()
    if saved:
        db.delete(saved)
        db.commit()
        return {"saved": False, "message": "Post unsaved"}
    else:
        new_save = models.SavedPost(post_id=post_id, user_id=current_user.id)
        db.add(new_save)
        db.commit()
        return {"saved": True, "message": "Post saved"}

@app.get("/posts/saved", response_model=List[schemas.PostOut])
def get_saved_posts(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    saved = db.query(models.SavedPost).filter(models.SavedPost.user_id == current_user.id).all()
    posts = [s.post for s in saved if s.post]
    return [prepare_post_out(p, current_user.id, db) for p in posts]

@app.get("/posts/user", response_model=List[schemas.PostOut])
def get_user_posts(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    posts = db.query(models.Post).filter(models.Post.user_id == current_user.id).order_by(models.Post.created_at.desc()).all()
    return [prepare_post_out(p, current_user.id, db) for p in posts]

# ─── Notifications ───
@app.get("/notifications", response_model=List[schemas.NotificationOut])
def get_notifications(
    skip: int = 0,
    limit: int = 50,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    notifs = db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id
    ).order_by(models.Notification.created_at.desc()).offset(skip).limit(limit).all()

    result = []
    for n in notifs:
        out = schemas.NotificationOut.from_orm(n)
        if n.actor_id:
            actor = db.query(models.User).filter(models.User.id == n.actor_id).first()
            out.actor_name = actor.full_name if actor else None
            out.actor_avatar = actor.profile_picture if actor else None
        result.append(out)
    return result

@app.get("/notifications/unread-count")
def get_unread_count(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    count = db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id,
        models.Notification.is_read == False
    ).count()
    return {"count": count}

@app.post("/notifications/read-all")
def mark_all_read(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id,
        models.Notification.is_read == False
    ).update({"is_read": True})
    db.commit()
    return {"message": "All notifications marked as read"}

@app.post("/notifications/{notif_id}/read")
def mark_one_read(notif_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    notif = db.query(models.Notification).filter(
        models.Notification.id == notif_id,
        models.Notification.user_id == current_user.id
    ).first()
    if notif:
        notif.is_read = True
        db.commit()
    return {"message": "Notification marked as read"}

@app.delete("/notifications")
def clear_notifications(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id
    ).delete(synchronize_session=False)
    db.commit()
    return {"message": "All notifications cleared"}

# ─── User Search & Social Endpoints ───
@app.get("/users/search", response_model=List[schemas.UserSearchOut])
@app.get("/api/users/search", response_model=List[schemas.UserSearchOut])
def search_users(
    q: str = Query(..., min_length=1),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: Optional[models.User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db)
):
    from sqlalchemy import or_
    search_term = f"%{q}%"
    current_id = current_user.id if current_user else None

    query = db.query(models.User).filter(
        or_(
            models.User.full_name.ilike(search_term),
            models.User.username.ilike(search_term),
            models.User.email.ilike(search_term),
            models.User.village.ilike(search_term),
        )
    )
    if current_id:
        query = query.filter(models.User.id != current_id)

    users = query.offset(skip).limit(limit).all()

    results = []
    for u in users:
        is_following = False
        if current_id:
            is_following = db.query(models.Follow).filter(
                models.Follow.follower_id == current_id,
                models.Follow.following_id == u.id
            ).first() is not None
        
        followers_cnt = db.query(models.Follow).filter(models.Follow.following_id == u.id).count()
        following_cnt = db.query(models.Follow).filter(models.Follow.follower_id == u.id).count()

        results.append(schemas.UserSearchOut(
            id=u.id,
            full_name=u.full_name,
            display_name=u.full_name or f"Farmer {u.id}",
            username=u.username,
            email=u.email,
            village=u.village or "Agricultural Hub",
            profile_picture=u.profile_picture,
            profile_photo=u.profile_picture,
            bio=u.bio,
            verified=u.is_verified,
            is_verified=u.is_verified,
            followers=followers_cnt,
            followers_count=followers_cnt,
            following_count=following_cnt,
            is_following=is_following,
            isFollowing=is_following,
        ))
    return results

@app.get("/users/suggested", response_model=List[schemas.UserSearchOut])
@app.get("/api/users/suggested", response_model=List[schemas.UserSearchOut])
def get_suggested_users(
    limit: int = Query(default=5, ge=1, le=20),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    following_ids = [f.following_id for f in db.query(models.Follow.following_id).filter(models.Follow.follower_id == current_user.id).all()]
    exclude_ids = set(following_ids)
    exclude_ids.add(current_user.id)

    query = db.query(models.User).filter(~models.User.id.in_(exclude_ids))
    
    suggested = []
    if current_user.crop_specialization or current_user.village:
        from sqlalchemy import or_
        matches = query.filter(
            or_(
                models.User.crop_specialization == current_user.crop_specialization,
                models.User.village == current_user.village
            )
        ).limit(limit).all()
        suggested.extend(matches)

    if len(suggested) < limit:
        already_picked = {u.id for u in suggested}
        already_picked.update(exclude_ids)
        remains = db.query(models.User).filter(~models.User.id.in_(already_picked)).limit(limit - len(suggested)).all()
        suggested.extend(remains)

    res = []
    for u in suggested:
        followers_cnt = db.query(models.Follow).filter(models.Follow.following_id == u.id).count()
        res.append(schemas.UserSearchOut(
            id=u.id,
            full_name=u.full_name,
            display_name=u.full_name or f"Farmer {u.id}",
            username=u.username,
            email=u.email,
            village=u.village or "Agricultural Hub",
            profile_picture=u.profile_picture,
            profile_photo=u.profile_picture,
            bio=u.bio,
            verified=u.is_verified,
            is_verified=u.is_verified,
            followers=followers_cnt,
            followers_count=followers_cnt,
            following_count=0,
            is_following=False,
            isFollowing=False
        ))
    return res

@app.get("/users/{user_id}/posts", response_model=List[schemas.PostOut])
@app.get("/api/users/{user_id}/posts", response_model=List[schemas.PostOut])
def get_user_posts(
    user_id: int,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, le=100),
    current_user: Optional[models.User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db)
):
    current_id = current_user.id if current_user else user_id
    posts = db.query(models.Post).filter(models.Post.user_id == user_id).order_by(models.Post.created_at.desc()).offset(skip).limit(limit).all()
    return [prepare_post_out(p, current_id, db) for p in posts]

@app.get("/users/{user_id}/followers", response_model=List[schemas.UserSearchOut])
@app.get("/api/users/{user_id}/followers", response_model=List[schemas.UserSearchOut])
def get_user_followers(
    user_id: int,
    current_user: Optional[models.User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db)
):
    current_id = current_user.id if current_user else None
    follows = db.query(models.Follow).filter(models.Follow.following_id == user_id).all()
    follower_users = [f.follower for f in follows if f.follower]

    res = []
    for u in follower_users:
        is_following = False
        if current_id:
            is_following = db.query(models.Follow).filter(
                models.Follow.follower_id == current_id,
                models.Follow.following_id == u.id
            ).first() is not None
        f_cnt = db.query(models.Follow).filter(models.Follow.following_id == u.id).count()
        res.append(schemas.UserSearchOut(
            id=u.id,
            full_name=u.full_name,
            display_name=u.full_name or f"Farmer {u.id}",
            username=u.username,
            email=u.email,
            village=u.village or "Agricultural Hub",
            profile_picture=u.profile_picture,
            profile_photo=u.profile_picture,
            bio=u.bio,
            verified=u.is_verified,
            is_verified=u.is_verified,
            followers=f_cnt,
            followers_count=f_cnt,
            following_count=0,
            is_following=is_following,
            isFollowing=is_following
        ))
    return res

@app.get("/users/{user_id}/following", response_model=List[schemas.UserSearchOut])
@app.get("/api/users/{user_id}/following", response_model=List[schemas.UserSearchOut])
def get_user_following(
    user_id: int,
    current_user: Optional[models.User] = Depends(get_optional_current_user),
    db: Session = Depends(get_db)
):
    current_id = current_user.id if current_user else None
    follows = db.query(models.Follow).filter(models.Follow.follower_id == user_id).all()
    following_users = [f.following for f in follows if f.following]

    res = []
    for u in following_users:
        is_following = False
        if current_id:
            is_following = db.query(models.Follow).filter(
                models.Follow.follower_id == current_id,
                models.Follow.following_id == u.id
            ).first() is not None
        f_cnt = db.query(models.Follow).filter(models.Follow.following_id == u.id).count()
        res.append(schemas.UserSearchOut(
            id=u.id,
            full_name=u.full_name,
            display_name=u.full_name or f"Farmer {u.id}",
            username=u.username,
            email=u.email,
            village=u.village or "Agricultural Hub",
            profile_picture=u.profile_picture,
            profile_photo=u.profile_picture,
            bio=u.bio,
            verified=u.is_verified,
            is_verified=u.is_verified,
            followers=f_cnt,
            followers_count=f_cnt,
            following_count=0,
            is_following=is_following,
            isFollowing=is_following
        ))
    return res

@app.get("/users/{user_id}/is-following")
@app.get("/api/users/{user_id}/is-following")
def is_following_user(user_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    following = db.query(models.Follow).filter(
        models.Follow.follower_id == current_user.id,
        models.Follow.following_id == user_id
    ).first() is not None
    return {"is_following": following, "isFollowing": following}

# ─── Chat AI ───
@app.post("/ai/chat", response_model=schemas.ChatMessage)
async def chat_with_ai(chat: schemas.ChatMessageCreate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    user_msg = models.ChatMessage(
        user_id=current_user.id,
        conversation_id=chat.conversation_id,
        message=chat.message,
        is_ai=False
    )
    db.add(user_msg)
    db.commit()

    # Get history for context, filter by conversation_id if provided
    query = db.query(models.ChatMessage).filter(models.ChatMessage.user_id == current_user.id)
    if chat.conversation_id:
        query = query.filter(models.ChatMessage.conversation_id == chat.conversation_id)
    else:
        query = query.filter(models.ChatMessage.conversation_id == None)

    history = query.order_by(models.ChatMessage.created_at.desc()).limit(10).all()
    history.reverse()

    # Fetch last 3 scans for smart context memory
    scans = db.query(models.CropScan).filter(
        models.CropScan.user_id == current_user.id,
        models.CropScan.is_valid_crop == True
    ).order_by(models.CropScan.created_at.desc()).limit(3).all()
    
    scan_context = ""
    if scans:
        scan_context = "User's recent crop scans:\n"
        for scan in scans:
            crop_name = scan.detected_object or "Crop"
            scan_context += f"- Crop: {crop_name}, Diagnosis: {scan.disease_name}, Severity: {scan.severity_level}, Date: {scan.created_at.strftime('%Y-%m-%d')}\n"

    ai_reply = await ai_service.ai_service.get_chat_response(chat.message, history, scan_context=scan_context)
    
    ai_msg = models.ChatMessage(
        user_id=current_user.id,
        conversation_id=chat.conversation_id,
        message=ai_reply,
        is_ai=True
    )
    db.add(ai_msg)
    db.commit()
    db.refresh(ai_msg)
    return ai_msg

@app.post("/chat")
async def chat_legacy(chat: schemas.ChatMessageCreate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    res = await chat_with_ai(chat, current_user, db)
    return {
        "response": res.message,
        "message": res.message,
        "reply": res.message,
        "id": res.id,
        "conversation_id": res.conversation_id,
        "is_ai": res.is_ai,
        "created_at": res.created_at
    }

@app.get("/chat/history", response_model=List[schemas.ChatMessage])
def get_chat_history(conversation_id: Optional[str] = None, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(models.ChatMessage).filter(models.ChatMessage.user_id == current_user.id)
    if conversation_id:
        query = query.filter(models.ChatMessage.conversation_id == conversation_id)
    return query.order_by(models.ChatMessage.created_at.asc()).all()

@app.delete("/chat/conversation/{conversation_id}")
def delete_chat_conversation(conversation_id: str, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(models.ChatMessage).filter(
        models.ChatMessage.user_id == current_user.id,
        models.ChatMessage.conversation_id == conversation_id
    ).delete(synchronize_session=False)
    db.commit()
    return {"status": "success", "message": "Conversation deleted"}

@app.put("/chat/conversation/{conversation_id}/title")
def rename_chat_conversation(conversation_id: str, title_update: schemas.ChatMessageCreate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    first_msg = db.query(models.ChatMessage).filter(
        models.ChatMessage.user_id == current_user.id,
        models.ChatMessage.conversation_id == conversation_id,
        models.ChatMessage.is_ai == False
    ).order_by(models.ChatMessage.created_at.asc()).first()
    
    if not first_msg:
        first_msg = models.ChatMessage(
            user_id=current_user.id,
            conversation_id=conversation_id,
            message=title_update.message,
            is_ai=False
        )
        db.add(first_msg)
    else:
        first_msg.message = title_update.message
        
    db.commit()
    return {"status": "success", "message": "Conversation renamed", "title": title_update.message}

@app.get("/chat/conversations", response_model=List[schemas.ConversationSummary])
def get_conversations(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """List all unique conversations for a user with preview and timestamp."""
    from sqlalchemy import func, case
    
    # Get all distinct conversation_ids with their first message and timestamp
    conversations = db.query(
        models.ChatMessage.conversation_id,
        func.min(models.ChatMessage.created_at).label('created_at'),
        func.max(models.ChatMessage.created_at).label('updated_at'),
        func.count(models.ChatMessage.id).label('message_count'),
    ).filter(
        models.ChatMessage.user_id == current_user.id,
        models.ChatMessage.conversation_id != None
    ).group_by(
        models.ChatMessage.conversation_id
    ).order_by(
        func.max(models.ChatMessage.created_at).desc()
    ).limit(50).all()
    
    results = []
    for conv in conversations:
        # Get first user message as preview
        first_msg = db.query(models.ChatMessage).filter(
            models.ChatMessage.user_id == current_user.id,
            models.ChatMessage.conversation_id == conv.conversation_id,
            models.ChatMessage.is_ai == False
        ).order_by(models.ChatMessage.created_at.asc()).first()
        
        preview = first_msg.message[:80] if first_msg else "New conversation"
        title = first_msg.message[:40] if first_msg else "New Chat"
        
        results.append(schemas.ConversationSummary(
            id=conv.conversation_id,
            title=title,
            preview=preview,
            created_at=conv.created_at,
            updated_at=conv.updated_at,
            message_count=conv.message_count,
        ))
    
    return results

# ─── Crop Scan (Trained PyTorch ML Engine) ───
@app.post("/ai/detect-disease", response_model=schemas.CropScanOut)
async def create_scan(scan: schemas.CropScanCreate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Run inference directly using trained PyTorch ResNet18 model
    analysis = await ai_service.ai_service.detect_disease(scan.image_url)

    db_scan = models.CropScan(
        user_id=current_user.id,
        image_url=scan.image_url,
        disease_name=analysis.get("disease_name", "Unknown"),
        confidence=analysis.get("confidence", 0.0),
        symptoms=analysis.get("symptoms"),
        causes=analysis.get("causes"),
        prevention=analysis.get("prevention"),
        pesticide_recommendations=analysis.get("pesticide_recommendations"),
        organic_treatment=analysis.get("organic_treatment"),
        irrigation_recommendations=analysis.get("irrigation_recommendations"),
        fertilizer_recommendations=analysis.get("fertilizer_recommendations"),
        recovery_steps=analysis.get("recovery_steps"),
        estimated_recovery_time=analysis.get("estimated_recovery_time"),
        severity_level=analysis.get("severity_level", "Warning"),
        health_score=analysis.get("health_score"),
        yield_impact=analysis.get("yield_impact"),
        pro_tips=analysis.get("pro_tips"),
        prevention_tips=analysis.get("prevention_tips"),
        is_valid_crop=True,
        detected_object=analysis.get("detected_object", "Crop"),
        rejection_reason=""
    )
    db.add(db_scan)
    db.commit()
    db.refresh(db_scan)

    result = schemas.CropScanOut.from_orm(db_scan)
    return result

@app.get("/ai/scan-history", response_model=List[schemas.CropScanOut])
def get_scan_history(
    limit: int = Query(default=20, le=50),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    scans = db.query(models.CropScan).filter(
        models.CropScan.user_id == current_user.id
    ).order_by(models.CropScan.created_at.desc()).limit(limit).all()
    return scans

# ─── Weather (Real via Open-Meteo API) ───
def _get_weather_condition(wmo_code: int) -> str:
    """Convert WMO weather code to human-readable condition."""
    conditions = {
        0: "Clear Sky", 1: "Mainly Clear", 2: "Partly Cloudy", 3: "Overcast",
        45: "Foggy", 48: "Depositing Rime Fog",
        51: "Light Drizzle", 53: "Moderate Drizzle", 55: "Dense Drizzle",
        61: "Slight Rain", 63: "Moderate Rain", 65: "Heavy Rain",
        66: "Light Freezing Rain", 67: "Heavy Freezing Rain",
        71: "Slight Snow", 73: "Moderate Snow", 75: "Heavy Snow",
        80: "Slight Rain Showers", 81: "Moderate Rain Showers", 82: "Violent Rain Showers",
        85: "Slight Snow Showers", 86: "Heavy Snow Showers",
        95: "Thunderstorm", 96: "Thunderstorm with Hail", 99: "Thunderstorm with Heavy Hail",
    }
    return conditions.get(wmo_code, "Partly Cloudy")

def _get_weather_icon(wmo_code: int) -> str:
    """Convert WMO weather code to icon string for frontend."""
    if wmo_code in [0, 1]:
        return "Sun"
    elif wmo_code in [2]:
        return "CloudSun"
    elif wmo_code in [3, 45, 48]:
        return "CloudIcon"
    elif wmo_code in [51, 53, 55, 61, 63, 65, 66, 67, 80, 81, 82]:
        return "CloudRain"
    elif wmo_code in [71, 73, 75, 85, 86]:
        return "Snowflake"
    elif wmo_code in [95, 96, 99]:
        return "CloudLightning"
    return "CloudSun"

def _generate_weather_alerts(temp: float, humidity: int, wind: float, rain_prob: int, uv: float) -> list:
    """Generate smart farming alerts based on weather conditions."""
    alerts = []
    
    if temp > 38:
        alerts.append({
            "type": "heat",
            "severity": "high",
            "message": f"🌡️ Extreme heat ({temp}°C)! Increase irrigation frequency. Provide shade for sensitive crops.",
            "icon": "Thermometer"
        })
    elif temp > 35:
        alerts.append({
            "type": "heat",
            "severity": "medium",
            "message": f"☀️ High temperature ({temp}°C). Water crops early morning or late evening.",
            "icon": "Sun"
        })
    
    if humidity > 80:
        alerts.append({
            "type": "disease_risk",
            "severity": "high",
            "message": f"⚠️ High humidity ({humidity}%). Increased risk of fungal diseases. Monitor crops closely.",
            "icon": "AlertTriangle"
        })
    
    if rain_prob > 70:
        alerts.append({
            "type": "rain",
            "severity": "medium",
            "message": f"🌧️ Heavy rain likely ({rain_prob}% chance). Postpone pesticide spraying. Check drainage systems.",
            "icon": "CloudRain"
        })
    elif rain_prob > 40:
        alerts.append({
            "type": "rain",
            "severity": "low",
            "message": f"🌦️ Rain expected ({rain_prob}% chance). Good time for fertilizer application before rain.",
            "icon": "CloudRain"
        })
    
    if wind > 25:
        alerts.append({
            "type": "wind",
            "severity": "high",
            "message": f"💨 Strong winds ({wind} km/h). Avoid spraying. Secure tall crops and greenhouse covers.",
            "icon": "Wind"
        })
    
    if uv > 8:
        alerts.append({
            "type": "uv",
            "severity": "medium",
            "message": f"🔆 Very high UV index ({uv}). Protect yourself during fieldwork. Consider shade nets for sensitive crops.",
            "icon": "Sun"
        })
    
    if not alerts:
        alerts.append({
            "type": "good",
            "severity": "low",
            "message": "✅ Weather conditions are favorable for farming activities today!",
            "icon": "CheckCircle"
        })
    
    return alerts

def _get_farming_suitability(temp: float, humidity: int, wind: float, rain_prob: int) -> str:
    """Determine farming suitability based on conditions."""
    score = 100
    if temp > 40 or temp < 5:
        score -= 40
    elif temp > 36 or temp < 10:
        score -= 20
    if humidity > 85:
        score -= 15
    if wind > 30:
        score -= 25
    elif wind > 20:
        score -= 10
    if rain_prob > 80:
        score -= 20
    elif rain_prob > 50:
        score -= 10
    
    if score >= 80:
        return "Excellent — Ideal for all field activities"
    elif score >= 60:
        return "Good — Most activities suitable"
    elif score >= 40:
        return "Fair — Limited outdoor activities recommended"
    else:
        return "Poor — Postpone field work if possible"

@app.get("/weather/current")
async def get_weather(
    lat: Optional[float] = Query(default=19.076, description="Latitude"),
    lon: Optional[float] = Query(default=72.8777, description="Longitude"),
):
    """Fetch real weather data from Open-Meteo API with farming insights."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as http_client:
            url = (
                f"https://api.open-meteo.com/v1/forecast?"
                f"latitude={lat}&longitude={lon}"
                f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
                f"weather_code,wind_speed_10m,surface_pressure"
                f"&daily=temperature_2m_max,temperature_2m_min,weather_code,"
                f"precipitation_probability_max,uv_index_max,sunrise,sunset"
                f"&timezone=auto&forecast_days=7"
            )
            resp = await http_client.get(url)
            resp.raise_for_status()
            data = resp.json()
        
        current = data.get("current", {})
        daily = data.get("daily", {})
        
        temp = current.get("temperature_2m", 32)
        humidity = current.get("relative_humidity_2m", 50)
        wind = current.get("wind_speed_10m", 10)
        weather_code = current.get("weather_code", 2)
        feels_like = current.get("apparent_temperature", temp)
        pressure = current.get("surface_pressure", 1013)
        
        # Daily data
        daily_highs = daily.get("temperature_2m_max", [34])
        daily_lows = daily.get("temperature_2m_min", [24])
        daily_codes = daily.get("weather_code", [2])
        daily_rain = daily.get("precipitation_probability_max", [0])
        daily_uv = daily.get("uv_index_max", [5])
        daily_sunrise = daily.get("sunrise", [])
        daily_sunset = daily.get("sunset", [])
        
        uv_index = daily_uv[0] if daily_uv else 5
        rain_prob = daily_rain[0] if daily_rain else 0
        
        # Build forecast
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        forecast = []
        for i in range(min(7, len(daily_highs))):
            day_dt = datetime.now() + timedelta(days=i)
            forecast.append({
                "day": day_names[day_dt.weekday()],
                "temp": round(daily_highs[i]) if i < len(daily_highs) else 30,
                "condition": _get_weather_condition(daily_codes[i] if i < len(daily_codes) else 2),
                "icon": _get_weather_icon(daily_codes[i] if i < len(daily_codes) else 2),
            })
        
        # Sunrise/sunset formatting
        sunrise_str = ""
        sunset_str = ""
        if daily_sunrise and len(daily_sunrise) > 0:
            try:
                sr = datetime.fromisoformat(daily_sunrise[0])
                sunrise_str = sr.strftime("%I:%M %p")
            except:
                sunrise_str = "06:00 AM"
        if daily_sunset and len(daily_sunset) > 0:
            try:
                ss = datetime.fromisoformat(daily_sunset[0])
                sunset_str = ss.strftime("%I:%M %p")
            except:
                sunset_str = "06:30 PM"
        
        # Generate alerts
        alerts = _generate_weather_alerts(temp, humidity, wind, rain_prob, uv_index)
        
        # Farming suitability
        farming_suit = _get_farming_suitability(temp, humidity, wind, rain_prob)
        
        # Soil moisture estimate
        if rain_prob > 70:
            soil_moisture = "High — Adequate moisture expected"
        elif rain_prob > 30:
            soil_moisture = "Moderate — Monitor irrigation needs"
        else:
            soil_moisture = "Low — Irrigation recommended"
        
        # Reverse geocode location name
        location = "India"
        try:
            geo_url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&zoom=10"
            async with httpx.AsyncClient(timeout=3.0) as geo_client:
                geo_resp = await geo_client.get(geo_url, headers={"User-Agent": "AgriNex/1.0"})
                if geo_resp.status_code == 200:
                    geo_data = geo_resp.json()
                    address = geo_data.get("address", {})
                    city = address.get("city") or address.get("town") or address.get("county") or address.get("state_district", "")
                    state = address.get("state", "")
                    if city and state:
                        location = f"{city}, {state}"
                    elif state:
                        location = f"{state}, India"
        except:
            location = "Maharashtra, India"
        
        return {
            "temp": round(temp, 1),
            "feels_like": round(feels_like, 1),
            "condition": _get_weather_condition(weather_code),
            "humidity": humidity,
            "wind": round(wind, 1),
            "uv_index": round(uv_index, 1),
            "rain_probability": rain_prob,
            "pressure": round(pressure, 1),
            "visibility": 10.0,
            "location": location,
            "sunrise": sunrise_str,
            "sunset": sunset_str,
            "daily_high": round(daily_highs[0], 1) if daily_highs else 34,
            "daily_low": round(daily_lows[0], 1) if daily_lows else 24,
            "soil_moisture": soil_moisture,
            "farming_suitability": farming_suit,
            "alerts": alerts,
            "forecast": forecast,
        }
    except Exception as e:
        logger.error(f"Weather API error: {e}")
        # Fallback to realistic mock data
        return {
            "temp": 32,
            "feels_like": 34,
            "condition": "Partly Cloudy",
            "humidity": 55,
            "wind": 12,
            "uv_index": 6.5,
            "rain_probability": 20,
            "pressure": 1013,
            "visibility": 10.0,
            "location": "Maharashtra, India",
            "sunrise": "05:42 AM",
            "sunset": "06:54 PM",
            "daily_high": 35,
            "daily_low": 24,
            "soil_moisture": "Moderate — Monitor irrigation needs",
            "farming_suitability": "Good — Most activities suitable",
            "alerts": [{"type": "good", "severity": "low", "message": "✅ Weather conditions are favorable for farming!", "icon": "CheckCircle"}],
            "forecast": [
                {"day": "Mon", "temp": 31, "condition": "Sunny", "icon": "Sun"},
                {"day": "Tue", "temp": 29, "condition": "Cloudy", "icon": "CloudIcon"},
                {"day": "Wed", "temp": 28, "condition": "Rain", "icon": "CloudRain"},
                {"day": "Thu", "temp": 30, "condition": "Sunny", "icon": "Sun"},
                {"day": "Fri", "temp": 32, "condition": "Partly Cloudy", "icon": "CloudSun"},
            ]
        }

# Legacy endpoint alias for backwards compat
@app.get("/weather/location")
async def get_weather_by_location(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
):
    return await get_weather(lat=lat, lon=lon)


# ─── DIRECT MESSAGING (DM) & WEBSOCKET ENDPOINTS ───

def check_user_blocked(db: Session, user1_id: int, user2_id: int) -> bool:
    if not user1_id or not user2_id or user1_id == user2_id:
        return False
    from sqlalchemy import or_, and_
    blocked = db.query(models.BlockedUser).filter(
        or_(
            and_(models.BlockedUser.blocker_id == user1_id, models.BlockedUser.blocked_id == user2_id),
            and_(models.BlockedUser.blocker_id == user2_id, models.BlockedUser.blocked_id == user1_id)
        )
    ).first()
    return blocked is not None

def get_blocked_user_ids(db: Session, user_id: int) -> set:
    if not user_id:
        return set()
    b1 = [b.blocked_id for b in db.query(models.BlockedUser.blocked_id).filter(models.BlockedUser.blocker_id == user_id).all()]
    b2 = [b.blocker_id for b in db.query(models.BlockedUser.blocker_id).filter(models.BlockedUser.blocked_id == user_id).all()]
    return set(b1 + b2)


def prepare_message_out(msg: models.Message, current_user_id: int, db: Session) -> schemas.MessageOut:
    content = "This message was deleted" if msg.is_deleted_everyone else msg.content

    reply_content = None
    reply_sender = None
    if msg.reply_to_id and not msg.is_deleted_everyone:
        parent_msg = db.query(models.Message).filter(models.Message.id == msg.reply_to_id).first()
        if parent_msg:
            reply_content = "This message was deleted" if parent_msg.is_deleted_everyone else parent_msg.content
            p_sender = db.query(models.User).filter(models.User.id == parent_msg.sender_id).first()
            if p_sender:
                reply_sender = p_sender.full_name or f"Farmer {p_sender.id}"

    read_entry = db.query(models.MessageRead).filter(
        models.MessageRead.message_id == msg.id,
        models.MessageRead.user_id != msg.sender_id
    ).first()
    status_str = read_entry.status if read_entry else "sent"

    sender_u = db.query(models.User).filter(models.User.id == msg.sender_id).first()
    sender_name = sender_u.full_name if sender_u else f"Farmer {msg.sender_id}"
    sender_avatar = sender_u.profile_picture if sender_u else None

    attachments_out = [schemas.MessageAttachmentOut.from_orm(a) for a in msg.attachments]
    reactions_out = [schemas.MessageReactionOut.from_orm(r) for r in msg.reactions]

    return schemas.MessageOut(
        id=msg.id,
        conversation_id=msg.conversation_id,
        sender_id=msg.sender_id,
        sender_name=sender_name,
        sender_avatar=sender_avatar,
        content=content,
        reply_to_id=msg.reply_to_id,
        reply_to_content=reply_content,
        reply_to_sender=reply_sender,
        is_edited=msg.is_edited,
        is_deleted_everyone=msg.is_deleted_everyone,
        created_at=msg.created_at,
        updated_at=msg.updated_at,
        status=status_str,
        attachments=attachments_out,
        reactions=reactions_out
    )

def prepare_conversation_out(conv: models.Conversation, current_user_id: int, db: Session) -> schemas.ConversationOut:
    curr_part = db.query(models.Participant).filter(
        models.Participant.conversation_id == conv.id,
        models.Participant.user_id == current_user_id
    ).first()

    is_pinned = curr_part.is_pinned if curr_part else False
    is_muted = curr_part.is_muted if curr_part else False
    is_archived = curr_part.is_archived if curr_part else False
    last_read_at = curr_part.last_read_at if curr_part else conv.created_at

    other_part = db.query(models.Participant).filter(
        models.Participant.conversation_id == conv.id,
        models.Participant.user_id != current_user_id
    ).first()

    other_user_out = None
    if other_part:
        ou = db.query(models.User).filter(models.User.id == other_part.user_id).first()
        if ou:
            status_entry = db.query(models.UserOnlineStatus).filter(models.UserOnlineStatus.user_id == ou.id).first()
            is_online = ws_manager.is_online(ou.id) or (status_entry.is_online if status_entry else False)
            last_seen = status_entry.last_seen if status_entry else None
            other_user_out = schemas.ConversationParticipantOut(
                id=other_part.id,
                user_id=ou.id,
                full_name=ou.full_name,
                username=ou.username,
                profile_picture=ou.profile_picture,
                is_verified=ou.is_verified,
                is_online=is_online,
                last_seen=last_seen,
                is_pinned=is_pinned,
                is_muted=is_muted,
                is_archived=is_archived
            )

    deleted_ids = [d.message_id for d in db.query(models.MessageDeletedForUser.message_id).filter(models.MessageDeletedForUser.user_id == current_user_id).all()]
    query_last = db.query(models.Message).filter(models.Message.conversation_id == conv.id)
    if deleted_ids:
        query_last = query_last.filter(~models.Message.id.in_(deleted_ids))
    last_msg = query_last.order_by(models.Message.created_at.desc()).first()

    last_msg_out = prepare_message_out(last_msg, current_user_id, db) if last_msg else None

    query_unread = db.query(models.Message).filter(
        models.Message.conversation_id == conv.id,
        models.Message.sender_id != current_user_id,
        models.Message.created_at > last_read_at
    )
    if deleted_ids:
        query_unread = query_unread.filter(~models.Message.id.in_(deleted_ids))
    unread_cnt = query_unread.count()

    return schemas.ConversationOut(
        id=conv.id,
        type=conv.type,
        title=conv.title,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        other_participant=other_user_out,
        last_message=last_msg_out,
        unread_count=unread_cnt,
        is_pinned=is_pinned,
        is_muted=is_muted,
        is_archived=is_archived
    )


@app.get("/messages", response_model=List[schemas.ConversationOut])
@app.get("/api/conversations", response_model=List[schemas.ConversationOut])
def get_user_conversations(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    parts = db.query(models.Participant).filter(models.Participant.user_id == current_user.id).all()
    conv_ids = [p.conversation_id for p in parts]
    if not conv_ids:
        return []

    convs = db.query(models.Conversation).filter(models.Conversation.id.in_(conv_ids)).order_by(models.Conversation.updated_at.desc()).all()
    res = [prepare_conversation_out(c, current_user.id, db) for c in convs]
    res.sort(key=lambda x: (not x.is_pinned, x.updated_at), reverse=True)
    return res


@app.post("/messages/start", response_model=schemas.ConversationOut)
@app.post("/api/conversations/start", response_model=schemas.ConversationOut)
def start_conversation(req: schemas.StartConversationRequest, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if req.target_user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot start a conversation with yourself")

    target = db.query(models.User).filter(models.User.id == req.target_user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target user not found")

    if check_user_blocked(db, current_user.id, req.target_user_id):
        raise HTTPException(status_code=403, detail="Cannot message this user due to block settings")

    p1 = db.query(models.Participant.conversation_id).filter(models.Participant.user_id == current_user.id).subquery()
    existing = db.query(models.Participant.conversation_id).filter(
        models.Participant.conversation_id.in_(p1),
        models.Participant.user_id == req.target_user_id
    ).first()

    if existing:
        conv = db.query(models.Conversation).filter(models.Conversation.id == existing.conversation_id).first()
    else:
        conv = models.Conversation(type="direct")
        db.add(conv)
        db.commit()
        db.refresh(conv)

        part1 = models.Participant(conversation_id=conv.id, user_id=current_user.id)
        part2 = models.Participant(conversation_id=conv.id, user_id=req.target_user_id)
        db.add_all([part1, part2])
        db.commit()

    return prepare_conversation_out(conv, current_user.id, db)


@app.get("/messages/{conversation_id}", response_model=List[schemas.MessageOut])
@app.get("/api/conversations/{conversation_id}/messages", response_model=List[schemas.MessageOut])
def get_conversation_messages(
    conversation_id: int,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    part = db.query(models.Participant).filter(
        models.Participant.conversation_id == conversation_id,
        models.Participant.user_id == current_user.id
    ).first()
    if not part:
        raise HTTPException(status_code=403, detail="Not a participant in this conversation")

    deleted_ids = [d.message_id for d in db.query(models.MessageDeletedForUser.message_id).filter(models.MessageDeletedForUser.user_id == current_user.id).all()]
    query = db.query(models.Message).filter(models.Message.conversation_id == conversation_id)
    if deleted_ids:
        query = query.filter(~models.Message.id.in_(deleted_ids))

    messages = query.order_by(models.Message.created_at.asc()).offset(skip).limit(limit).all()

    unread_messages = [m for m in messages if m.sender_id != current_user.id]
    if unread_messages:
        for m in unread_messages:
            read_entry = db.query(models.MessageRead).filter(
                models.MessageRead.message_id == m.id,
                models.MessageRead.user_id == current_user.id
            ).first()
            if not read_entry:
                db.add(models.MessageRead(message_id=m.id, user_id=current_user.id, status="seen"))
            else:
                read_entry.status = "seen"
        part.last_read_at = datetime.utcnow()
        db.commit()

        other_parts = db.query(models.Participant.user_id).filter(
            models.Participant.conversation_id == conversation_id,
            models.Participant.user_id != current_user.id
        ).all()
        other_uids = [p.user_id for p in other_parts]
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(ws_manager.broadcast_read_receipt(conversation_id, current_user.id, [m.id for m in unread_messages], other_uids))
        except Exception:
            pass

    return [prepare_message_out(m, current_user.id, db) for m in messages]


@app.post("/messages/send", response_model=schemas.MessageOut)
@app.post("/api/messages/send", response_model=schemas.MessageOut)
def send_message(msg_in: schemas.MessageCreate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    conv_id = msg_in.conversation_id

    if not conv_id and msg_in.recipient_id:
        start_res = start_conversation(schemas.StartConversationRequest(target_user_id=msg_in.recipient_id), current_user, db)
        conv_id = start_res.id

    if not conv_id:
        raise HTTPException(status_code=400, detail="Must specify conversation_id or recipient_id")

    part = db.query(models.Participant).filter(
        models.Participant.conversation_id == conv_id,
        models.Participant.user_id == current_user.id
    ).first()
    if not part:
        raise HTTPException(status_code=403, detail="Not a participant in this conversation")

    other_parts = db.query(models.Participant.user_id).filter(
        models.Participant.conversation_id == conv_id,
        models.Participant.user_id != current_user.id
    ).all()
    other_uids = [p.user_id for p in other_parts]

    for ou_id in other_uids:
        if check_user_blocked(db, current_user.id, ou_id):
            blocked_by_me = db.query(models.BlockedUser).filter(
                models.BlockedUser.blocker_id == current_user.id,
                models.BlockedUser.blocked_id == ou_id
            ).first() is not None
            if blocked_by_me:
                raise HTTPException(status_code=403, detail="You cannot send messages because you have blocked this user.")
            else:
                raise HTTPException(status_code=403, detail="You cannot send messages because this user has blocked you.")


    if not msg_in.content and not msg_in.attachments:
        raise HTTPException(status_code=400, detail="Message content or image attachment required")

    message = models.Message(
        conversation_id=conv_id,
        sender_id=current_user.id,
        content=msg_in.content.strip() if msg_in.content else None,
        reply_to_id=msg_in.reply_to_id
    )
    db.add(message)
    db.commit()
    db.refresh(message)

    for att_url in msg_in.attachments:
        if att_url.strip():
            db.add(models.MessageAttachment(message_id=message.id, url=att_url.strip(), file_type="image"))
    db.commit()
    db.refresh(message)

    conv = db.query(models.Conversation).filter(models.Conversation.id == conv_id).first()
    if conv:
        conv.updated_at = datetime.utcnow()
        db.commit()

    msg_out = prepare_message_out(message, current_user.id, db)

    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(ws_manager.broadcast_message(msg_out.dict(), other_uids + [current_user.id]))
    except Exception as e:
        logger.warning(f"WebSocket broadcast error: {e}")

    for ou_id in other_uids:
        actor_name = current_user.full_name or f"Farmer {current_user.id}"
        create_notification(db, ou_id, current_user.id, "MESSAGE", f"{actor_name} sent you a message")

    return msg_out


@app.patch("/messages/edit", response_model=schemas.MessageOut)
@app.patch("/api/messages/{message_id}", response_model=schemas.MessageOut)
def edit_message(
    msg_edit: schemas.MessageEdit,
    message_id: Optional[int] = None,
    msg_id: Optional[int] = Query(None),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    target_id = message_id or msg_id
    if not target_id:
        raise HTTPException(status_code=400, detail="Message ID required")

    message = db.query(models.Message).filter(models.Message.id == target_id, models.Message.sender_id == current_user.id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found or unauthorized")

    time_diff = (datetime.utcnow() - message.created_at).total_seconds()
    if time_diff > 900:
        raise HTTPException(status_code=400, detail="Messages can only be edited within 15 minutes of sending")

    message.content = msg_edit.content.strip()
    message.is_edited = True
    db.commit()
    db.refresh(message)

    msg_out = prepare_message_out(message, current_user.id, db)

    other_parts = db.query(models.Participant.user_id).filter(
        models.Participant.conversation_id == message.conversation_id
    ).all()
    uids = [p.user_id for p in other_parts]
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(ws_manager.broadcast_to_users(uids, {"type": "message_edited", "message": msg_out.dict()}))
    except Exception:
        pass

    return msg_out


@app.delete("/messages/delete")
@app.delete("/api/messages/{message_id}")
def delete_message(
    message_id: Optional[int] = None,
    msg_id: Optional[int] = Query(None),
    delete_type: str = Query(default="for_me", description="for_me or everyone"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    target_id = message_id or msg_id
    if not target_id:
        raise HTTPException(status_code=400, detail="Message ID required")

    message = db.query(models.Message).filter(models.Message.id == target_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    part = db.query(models.Participant).filter(
        models.Participant.conversation_id == message.conversation_id,
        models.Participant.user_id == current_user.id
    ).first()
    if not part:
        raise HTTPException(status_code=403, detail="Not a participant in this conversation")

    if delete_type == "everyone":
        if message.sender_id != current_user.id:
            raise HTTPException(status_code=403, detail="Only sender can delete message for everyone")
        message.is_deleted_everyone = True
        message.content = None
        db.commit()
    else:
        existing = db.query(models.MessageDeletedForUser).filter(
            models.MessageDeletedForUser.message_id == target_id,
            models.MessageDeletedForUser.user_id == current_user.id
        ).first()
        if not existing:
            db.add(models.MessageDeletedForUser(message_id=target_id, user_id=current_user.id))
            db.commit()

    other_parts = db.query(models.Participant.user_id).filter(
        models.Participant.conversation_id == message.conversation_id
    ).all()
    uids = [p.user_id for p in other_parts]
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(ws_manager.broadcast_to_users(uids, {
                "type": "message_deleted",
                "message_id": target_id,
                "delete_type": delete_type,
                "user_id": current_user.id
            }))
    except Exception:
        pass

    return {"message": "Message deleted successfully", "delete_type": delete_type}


@app.post("/messages/read")
@app.post("/api/messages/{conversation_id}/read")
def mark_messages_read(
    conversation_id: Optional[int] = None,
    conv_id: Optional[int] = Query(None),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    target_id = conversation_id or conv_id
    if not target_id:
        raise HTTPException(status_code=400, detail="Conversation ID required")

    part = db.query(models.Participant).filter(
        models.Participant.conversation_id == target_id,
        models.Participant.user_id == current_user.id
    ).first()
    if not part:
        raise HTTPException(status_code=403, detail="Not a participant")

    part.last_read_at = datetime.utcnow()

    unread_msgs = db.query(models.Message).filter(
        models.Message.conversation_id == target_id,
        models.Message.sender_id != current_user.id
    ).all()

    for m in unread_msgs:
        read_e = db.query(models.MessageRead).filter(
            models.MessageRead.message_id == m.id,
            models.MessageRead.user_id == current_user.id
        ).first()
        if not read_e:
            db.add(models.MessageRead(message_id=m.id, user_id=current_user.id, status="seen"))
        else:
            read_e.status = "seen"
    db.commit()

    other_parts = db.query(models.Participant.user_id).filter(
        models.Participant.conversation_id == target_id,
        models.Participant.user_id != current_user.id
    ).all()
    other_uids = [p.user_id for p in other_parts]
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(ws_manager.broadcast_read_receipt(target_id, current_user.id, [m.id for m in unread_msgs], other_uids))
    except Exception:
        pass

    return {"status": "success", "conversation_id": target_id}


@app.post("/messages/reaction", response_model=schemas.MessageOut)
@app.post("/api/messages/{message_id}/react", response_model=schemas.MessageOut)
def toggle_message_reaction(
    reaction_in: schemas.MessageReactionCreate,
    message_id: Optional[int] = None,
    msg_id: Optional[int] = Query(None),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    target_id = message_id or msg_id
    if not target_id:
        raise HTTPException(status_code=400, detail="Message ID required")

    message = db.query(models.Message).filter(models.Message.id == target_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    part = db.query(models.Participant).filter(
        models.Participant.conversation_id == message.conversation_id,
        models.Participant.user_id == current_user.id
    ).first()
    if not part:
        raise HTTPException(status_code=403, detail="Not a participant")

    existing = db.query(models.MessageReaction).filter(
        models.MessageReaction.message_id == target_id,
        models.MessageReaction.user_id == current_user.id,
        models.MessageReaction.emoji == reaction_in.emoji
    ).first()

    if existing:
        db.delete(existing)
    else:
        db.add(models.MessageReaction(message_id=target_id, user_id=current_user.id, emoji=reaction_in.emoji))
    db.commit()
    db.refresh(message)

    msg_out = prepare_message_out(message, current_user.id, db)

    all_parts = db.query(models.Participant.user_id).filter(
        models.Participant.conversation_id == message.conversation_id
    ).all()
    uids = [p.user_id for p in all_parts]
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(ws_manager.broadcast_to_users(uids, {"type": "message_reaction", "message": msg_out.dict()}))
    except Exception:
        pass

    return msg_out


@app.post("/api/conversations/{conversation_id}/pin")
def pin_conversation(conversation_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    part = db.query(models.Participant).filter(
        models.Participant.conversation_id == conversation_id,
        models.Participant.user_id == current_user.id
    ).first()
    if not part:
        raise HTTPException(status_code=404, detail="Conversation not found")
    part.is_pinned = not part.is_pinned
    db.commit()
    return {"is_pinned": part.is_pinned}


@app.post("/api/conversations/{conversation_id}/mute")
def mute_conversation(conversation_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    part = db.query(models.Participant).filter(
        models.Participant.conversation_id == conversation_id,
        models.Participant.user_id == current_user.id
    ).first()
    if not part:
        raise HTTPException(status_code=404, detail="Conversation not found")
    part.is_muted = not part.is_muted
    db.commit()
    return {"is_muted": part.is_muted}


@app.post("/api/conversations/{conversation_id}/archive")
def archive_conversation(conversation_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    part = db.query(models.Participant).filter(
        models.Participant.conversation_id == conversation_id,
        models.Participant.user_id == current_user.id
    ).first()
    if not part:
        raise HTTPException(status_code=404, detail="Conversation not found")
    part.is_archived = not part.is_archived
    db.commit()
    return {"is_archived": part.is_archived}


# ─── BLOCK USER SYSTEM ───

@app.get("/users/{user_id}/block-status", response_model=schemas.BlockStatusOut)
@app.get("/api/users/{user_id}/block-status", response_model=schemas.BlockStatusOut)
def get_user_block_status(user_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    blocked_by_me = db.query(models.BlockedUser).filter(
        models.BlockedUser.blocker_id == current_user.id,
        models.BlockedUser.blocked_id == user_id
    ).first() is not None

    blocked_by_them = db.query(models.BlockedUser).filter(
        models.BlockedUser.blocker_id == user_id,
        models.BlockedUser.blocked_id == current_user.id
    ).first() is not None

    return schemas.BlockStatusOut(
        is_blocked=blocked_by_me or blocked_by_them,
        blocked_by_me=blocked_by_me,
        blocked_by_them=blocked_by_them,
        user_id=user_id
    )


@app.post("/users/{user_id}/block")
@app.post("/api/users/{user_id}/block")
def block_user(user_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot block yourself")

    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    existing = db.query(models.BlockedUser).filter(
        models.BlockedUser.blocker_id == current_user.id,
        models.BlockedUser.blocked_id == user_id
    ).first()

    if existing:
        raise HTTPException(status_code=409, detail="User is already blocked")

    db.add(models.BlockedUser(blocker_id=current_user.id, blocked_id=user_id))

    f1 = db.query(models.Follow).filter(models.Follow.follower_id == current_user.id, models.Follow.following_id == user_id).first()
    if f1:
        db.delete(f1)
    f2 = db.query(models.Follow).filter(models.Follow.follower_id == user_id, models.Follow.following_id == current_user.id).first()
    if f2:
        db.delete(f2)

    db.commit()

    return {"blocked": True, "user_id": user_id}


@app.delete("/users/{user_id}/block")
@app.delete("/api/users/{user_id}/block")
def unblock_user(user_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    existing = db.query(models.BlockedUser).filter(
        models.BlockedUser.blocker_id == current_user.id,
        models.BlockedUser.blocked_id == user_id
    ).first()

    if existing:
        db.delete(existing)
        db.commit()

    return {"blocked": False, "user_id": user_id}


@app.get("/users/blocked", response_model=List[schemas.UserSearchOut])
@app.get("/api/users/blocked", response_model=List[schemas.UserSearchOut])

def get_blocked_users(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    blocked_entries = db.query(models.BlockedUser).filter(models.BlockedUser.blocker_id == current_user.id).all()
    b_ids = [b.blocked_id for b in blocked_entries]
    if not b_ids:
        return []
    users = db.query(models.User).filter(models.User.id.in_(b_ids)).all()
    return [
        schemas.UserSearchOut(
            id=u.id,
            full_name=u.full_name,
            display_name=u.full_name or f"Farmer {u.id}",
            username=u.username,
            email=u.email,
            village=u.village or "Agricultural Hub",
            profile_picture=u.profile_picture,
            profile_photo=u.profile_picture,
            bio=u.bio,
            verified=u.is_verified,
            is_verified=u.is_verified,
            followers=0,
            followers_count=0,
            following_count=0,
            is_following=False,
            isFollowing=False
        ) for u in users
    ]


# ─── MEDIA UPLOAD ENDPOINT ───

@app.post("/api/media/upload")
async def upload_media_file(file: UploadFile = File(...), current_user: models.User = Depends(get_current_user)):
    try:
        contents = await file.read()
        import base64
        ext = file.filename.split(".")[-1] if file.filename and "." in file.filename else "jpg"
        mime_type = file.content_type or f"image/{ext}"
        base64_str = base64.b64encode(contents).decode("utf-8")
        data_url = f"data:{mime_type};base64,{base64_str}"
        return {"url": data_url, "filename": file.filename}
    except Exception as e:
        logger.error(f"Media upload error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to upload media: {str(e)}")


# ─── WEBSOCKET ROUTE ───

@app.websocket("/ws/chat/{user_id}")
async def websocket_chat_endpoint(websocket: WebSocket, user_id: int, db: Session = Depends(get_db)):
    await ws_manager.connect(websocket, user_id)

    status_entry = db.query(models.UserOnlineStatus).filter(models.UserOnlineStatus.user_id == user_id).first()
    if not status_entry:
        status_entry = models.UserOnlineStatus(user_id=user_id, is_online=True, last_seen=datetime.utcnow())
        db.add(status_entry)
    else:
        status_entry.is_online = True
        status_entry.last_seen = datetime.utcnow()
    db.commit()

    try:
        while True:
            data_text = await websocket.receive_text()
            try:
                data = json.loads(data_text)
                msg_type = data.get("type")

                if msg_type == "typing":
                    conv_id = data.get("conversation_id")
                    is_typing = data.get("is_typing", False)
                    sender_name = data.get("sender_name", f"Farmer {user_id}")
                    if conv_id:
                        other_parts = db.query(models.Participant.user_id).filter(
                            models.Participant.conversation_id == conv_id,
                            models.Participant.user_id != user_id
                        ).all()
                        target_ids = [p.user_id for p in other_parts]
                        await ws_manager.broadcast_typing(conv_id, user_id, sender_name, is_typing, target_ids)

                elif msg_type == "ping":
                    await websocket.send_json({"type": "pong"})

            except Exception as parse_err:
                logger.warning(f"WS data parse error for user {user_id}: {parse_err}")

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, user_id)
        status_entry = db.query(models.UserOnlineStatus).filter(models.UserOnlineStatus.user_id == user_id).first()
        if status_entry:
            status_entry.is_online = False
            status_entry.last_seen = datetime.utcnow()
            db.commit()


@app.get("/ai/model-info")
def get_ai_model_info():
    """Returns runtime status and provider configuration of AgriNex AI services."""
    llama_model = os.getenv("LLAMA_MODEL", "llama-3.3-70b-versatile")
    scanner_info = vision_engine.get_model_info()

    return {
        "disease_scanner": scanner_info,
        "ai_chat": {
            "provider": "groq",
            "model": llama_model,
            "status": "configured"
        },
        "gemini": {
            "provider": "gemini",
            "status": "disabled"
        }
    }


