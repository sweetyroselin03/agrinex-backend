from fastapi import FastAPI, Depends, HTTPException, status, Query
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
from .database import engine, get_db
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)

# Create tables
models.Base.metadata.create_all(bind=engine)

logger_startup = logging.getLogger("uvicorn.error")
logger_startup.info("[Startup] Database tables synchronized via SQLAlchemy ORM.")

ENV = os.getenv("ENV", "production")
show_docs = os.getenv("SHOW_DOCS", "false").lower() in ("true", "1", "yes") or ENV == "development"

app = FastAPI(
    title="AgriNex AI Enterprise Backend",
    docs_url="/docs" if show_docs else None,
    redoc_url="/redoc" if show_docs else None,
)

# CORS configuration
allowed_origins_str = os.getenv("ALLOWED_ORIGINS", "")
if allowed_origins_str:
    allow_origins = [origin.strip() for origin in allowed_origins_str.split(",") if origin.strip()]
else:
    allow_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True if allow_origins != ["*"] else False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)

logger = logging.getLogger("uvicorn.error")
logger.info("[Startup] Application ready. Brevo Transactional Email API will be used on-demand during OTP requests.")

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
def update_profile(user_update: schemas.UserUpdate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    for key, value in user_update.dict(exclude_unset=True).items():
        setattr(current_user, key, value)
    db.commit()
    db.refresh(current_user)
    
    followers_count = db.query(models.Follow).filter(models.Follow.following_id == current_user.id).count()
    following_count = db.query(models.Follow).filter(models.Follow.follower_id == current_user.id).count()
    posts_count = db.query(models.Post).filter(models.Post.user_id == current_user.id).count()
    
    user_out = schemas.UserOut.from_orm(current_user)
    user_out.followers_count = followers_count
    user_out.following_count = following_count
    user_out.posts_count = posts_count
    return user_out

@app.delete("/user")
def delete_account(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.delete(current_user)
    db.commit()
    return {"message": "Account deleted successfully"}

@app.get("/users/{user_id}", response_model=schemas.UserOut)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    followers_count = db.query(models.Follow).filter(models.Follow.following_id == user_id).count()
    following_count = db.query(models.Follow).filter(models.Follow.follower_id == user_id).count()
    posts_count = db.query(models.Post).filter(models.Post.user_id == user_id).count()
    
    user_out = schemas.UserOut.from_orm(user)
    user_out.followers_count = followers_count
    user_out.following_count = following_count
    user_out.posts_count = posts_count
    return user_out

@app.post("/users/{user_id}/follow", response_model=schemas.FollowOut)
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

    if follow:
        db.delete(follow)
        db.commit()
        following = False
    else:
        new_follow = models.Follow(follower_id=current_user.id, following_id=user_id)
        db.add(new_follow)
        db.commit()
        following = True
        # Notify the followed user (NOT the follower)
        actor_name = current_user.full_name or f"Farmer {current_user.id}"
        create_notification(db, user_id, current_user.id, "FOLLOW",
            f"{actor_name} started following you")

    followers_count = db.query(models.Follow).filter(models.Follow.following_id == user_id).count()
    following_count = db.query(models.Follow).filter(models.Follow.follower_id == current_user.id).count()
    return schemas.FollowOut(following=following, followers_count=followers_count, following_count=following_count)

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

@app.get("/posts", response_model=List[schemas.PostOut])
def get_feed(skip: int = 0, limit: int = 20, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    posts = db.query(models.Post).order_by(models.Post.created_at.desc()).offset(skip).limit(limit).all()
    return [prepare_post_out(p, current_user.id, db) for p in posts]

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

# ─── User Search ───
@app.get("/users/search", response_model=List[schemas.UserSearchOut])
def search_users(
    q: str = Query(..., min_length=1),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    from sqlalchemy import or_, func
    search = f"%{q}%"
    users = db.query(models.User).filter(
        models.User.id != current_user.id,
        or_(
            models.User.full_name.ilike(search),
            models.User.email.ilike(search),
            models.User.username.ilike(search),
        )
    ).limit(20).all()

    result = []
    for u in users:
        is_following = db.query(models.Follow).filter(
            models.Follow.follower_id == current_user.id,
            models.Follow.following_id == u.id
        ).first() is not None
        followers_count = db.query(models.Follow).filter(models.Follow.following_id == u.id).count()
        following_count = db.query(models.Follow).filter(models.Follow.follower_id == u.id).count()
        out = schemas.UserSearchOut(
            id=u.id,
            full_name=u.full_name,
            username=u.username,
            email=u.email,
            profile_picture=u.profile_picture,
            bio=u.bio,
            is_verified=u.is_verified,
            is_following=is_following,
            followers_count=followers_count,
            following_count=following_count,
        )
        result.append(out)
    return result

@app.get("/users/{user_id}/is-following")
def is_following_user(user_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    following = db.query(models.Follow).filter(
        models.Follow.follower_id == current_user.id,
        models.Follow.following_id == user_id
    ).first() is not None
    return {"is_following": following}

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

# ─── Crop Scan (Two-Stage Validation Pipeline) ───
@app.post("/ai/detect-disease", response_model=schemas.CropScanOut)
async def create_scan(scan: schemas.CropScanCreate, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    
    # ━━━ STAGE 1: Validate that the image contains a crop/plant ━━━
    validation = await ai_service.ai_service.validate_crop_image(scan.image_url)
    
    if not validation.get("is_valid", True):
        # Image rejected — return immediately without running disease detection
        detected = validation.get("detected_object", "non-agricultural object")
        reason = validation.get("rejection_reason", "This image does not contain a detectable crop or plant.")
        quality_issue = validation.get("quality_issue")
        
        disease_name = "Quality Issue" if quality_issue else "Invalid Crop Scan"
        
        return schemas.CropScanOut(
            id=-1,
            user_id=current_user.id,
            image_url=scan.image_url,
            disease_name=disease_name,
            confidence=validation.get("confidence", 0.0),
            is_valid_crop=False,
            severity_level="Critical",
            symptoms=reason,
            causes=f"Detected: {detected}. {reason}",
            prevention="Align a plant leaf, fruit, or stem in the camera frame for accurate disease detection.",
            detected_object=detected,
            rejection_reason=reason,
            created_at=datetime.utcnow()
        )
    
    # ━━━ STAGE 2: Run disease detection (only for validated crop images) ━━━
    analysis = await ai_service.ai_service.detect_disease(scan.image_url)
    
    if not analysis:
        analysis = {
            "is_valid_crop": True,
            "disease_name": "Analysis Unavailable",
            "confidence_level": 0.0,
            "severity_level": "Warning",
            "symptoms": "AI service temporarily unavailable",
            "causes": "Server connectivity issue",
            "prevention": "Please try again in a moment",
            "treatment": "Retry scan or consult local agriculture expert",
            "organic_treatment": "Consult local expert",
            "pesticide_recommendations": "Consult local dealer",
            "irrigation_recommendations": "Maintain regular schedule",
            "fertilizer_recommendations": "Balanced NPK",
            "recovery_steps": "Retry scan when service is available",
            "estimated_recovery_time": "N/A",
            "weather_risk": "N/A",
            "prevention_tips": "Regular monitoring recommended",
        }

    # Confidence check
    confidence = analysis.get("confidence_level", 0.0)
    if confidence < 65.0:
        return schemas.CropScanOut(
            id=-1,
            user_id=current_user.id,
            image_url=scan.image_url,
            disease_name="Quality Issue",
            confidence=confidence,
            is_valid_crop=False,
            severity_level="Critical",
            symptoms="Unable to confidently identify disease. Please retake image in good lighting.",
            causes="Low confidence match.",
            prevention="Make sure the leaf is in focus and there is adequate lighting.",
            detected_object=analysis.get("crop_type", "crop"),
            rejection_reason="Unable to confidently identify disease.",
            created_at=datetime.utcnow()
        )
    
    db_scan = models.CropScan(
        user_id=current_user.id,
        image_url=scan.image_url,
        disease_name=analysis.get("disease_name", "Unknown"),
        confidence=analysis.get("confidence_level", 0.0),
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
        detected_object=analysis.get("crop_type", "Unknown"),
        rejection_reason=""
    )
    db.add(db_scan)
    db.commit()
    db.refresh(db_scan)
    
    # Return with extra fields from analysis
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
