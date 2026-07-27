import json
from pydantic import BaseModel, validator
from typing import Optional, List
from datetime import datetime


# ─── User ────────────────────────────────────────────────────────────────────
class UserBase(BaseModel):
    email: str
    phone: Optional[str] = None

class UserCreate(UserBase):
    pass

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    username: Optional[str] = None
    phone: Optional[str] = None
    village: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    farm_size: Optional[str] = None
    experience: Optional[str] = None
    crop_specialization: Optional[str] = None
    crop_types: Optional[str] = None
    profile_picture: Optional[str] = None
    bio: Optional[str] = None
    website: Optional[str] = None

class UserOut(BaseModel):
    id: int
    email: str
    phone: Optional[str] = None
    full_name: Optional[str] = None
    display_name: Optional[str] = None
    username: Optional[str] = None
    village: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    farm_size: Optional[str] = None
    experience: Optional[str] = None
    crop_specialization: Optional[str] = None
    specialization: Optional[str] = None
    crop_types: Optional[str] = None
    profile_picture: Optional[str] = None
    profile_photo: Optional[str] = None
    bio: Optional[str] = None
    website: Optional[str] = None
    is_verified: Optional[bool] = False
    created_at: Optional[datetime] = None
    joined_date: Optional[datetime] = None
    followers_count: Optional[int] = 0
    following_count: Optional[int] = 0
    posts_count: Optional[int] = 0
    is_following: Optional[bool] = False
    isFollowing: Optional[bool] = False

    class Config:
        from_attributes = True

# Keep legacy alias
User = UserOut


class UserSearchOut(BaseModel):
    id: int
    full_name: Optional[str] = None
    display_name: Optional[str] = None
    username: Optional[str] = None
    email: str
    village: Optional[str] = None
    profile_picture: Optional[str] = None
    profile_photo: Optional[str] = None
    bio: Optional[str] = None
    verified: Optional[bool] = True
    is_verified: Optional[bool] = True
    followers: Optional[int] = 0
    followers_count: Optional[int] = 0
    following_count: Optional[int] = 0
    is_following: Optional[bool] = False
    isFollowing: Optional[bool] = False

    class Config:
        from_attributes = True


# ─── Auth ─────────────────────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    full_name: str
    email: str
    phone: str

class PasswordSetRequest(BaseModel):
    email: str
    password: str

class OTPRequest(BaseModel):
    email: str

class LoginRequest(BaseModel):
    email: str
    password: str

class OTPVerify(BaseModel):
    email: str
    otp: str

class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserOut
    is_new: Optional[bool] = False


class ForgotPasswordRequest(BaseModel):
    email: str


class GoogleLoginRequest(BaseModel):
    id_token: str
    profile: dict


class CheckAccountRequest(BaseModel):
    identifier: str


class ResetPasswordRequest(BaseModel):
    email: str
    otp: str
    new_password: str

class RefreshTokenRequest(BaseModel):
    refresh_token: str


# ─── Post ─────────────────────────────────────────────────────────────────────
class PostCreate(BaseModel):
    content: str
    image_url: Optional[str] = None
    images: Optional[List[str]] = None
    hashtags: Optional[str] = None
    location: Optional[str] = None
    crop_category: Optional[str] = None

class PostUpdate(BaseModel):
    content: Optional[str] = None
    image_url: Optional[str] = None
    images: Optional[List[str]] = None
    hashtags: Optional[str] = None
    location: Optional[str] = None
    crop_category: Optional[str] = None

class PostOut(BaseModel):
    id: int
    user_id: int
    content: str
    image_url: Optional[str] = None
    images: Optional[List[str]] = []
    hashtags: Optional[str] = None
    location: Optional[str] = None
    crop_category: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    likes_count: Optional[int] = 0
    comments_count: Optional[int] = 0
    is_liked: Optional[bool] = False
    is_saved: Optional[bool] = False
    author_name: Optional[str] = None
    author_avatar: Optional[str] = None
    author_verified: Optional[bool] = False

    @validator('images', pre=True)
    def parse_images(cls, v):
        if v is None:
            return []
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                return parsed if isinstance(parsed, list) else []
            except Exception:
                return []
        return []

    class Config:
        from_attributes = True

# Keep legacy alias
Post = PostOut


# ─── Like ─────────────────────────────────────────────────────────────────────
class LikeOut(BaseModel):
    liked: bool
    likes_count: int


# ─── Comment ──────────────────────────────────────────────────────────────────
class CommentCreate(BaseModel):
    content: str
    parent_id: Optional[int] = None

class CommentOut(BaseModel):
    id: int
    user_id: int
    post_id: int
    content: str
    parent_id: Optional[int] = None
    created_at: datetime
    author_name: Optional[str] = None
    author_avatar: Optional[str] = None
    replies: Optional[List['CommentOut']] = []

    class Config:
        from_attributes = True

CommentOut.model_rebuild()


# ─── Follow ───────────────────────────────────────────────────────────────────
class FollowOut(BaseModel):
    following: bool
    isFollowing: bool
    is_following: bool
    followersCount: int
    followers_count: int
    followingCount: int
    following_count: int

    class Config:
        from_attributes = True


# ─── Notification ─────────────────────────────────────────────────────────────
class NotificationOut(BaseModel):
    id: int
    user_id: int
    type: str
    message: str
    is_read: bool
    created_at: datetime
    post_id: Optional[int] = None
    actor_id: Optional[int] = None
    actor_name: Optional[str] = None
    actor_avatar: Optional[str] = None

    class Config:
        from_attributes = True


# ─── SavedPost ────────────────────────────────────────────────────────────────
class SaveOut(BaseModel):
    saved: bool


# ─── Chat ─────────────────────────────────────────────────────────────────────
class ChatMessageCreate(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    language: Optional[str] = None

class ChatMessage(BaseModel):
    id: int
    user_id: int
    conversation_id: Optional[str] = None
    message: str
    is_ai: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationSummary(BaseModel):
    id: str
    title: str
    preview: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    message_count: int = 0

    class Config:
        from_attributes = True


# ─── Crop Scan ────────────────────────────────────────────────────────────────
class CropScanCreate(BaseModel):
    image_url: str

class CropScanOut(BaseModel):
    id: int
    user_id: int
    image_url: str
    disease_name: str
    confidence: float
    is_valid_crop: Optional[bool] = True
    severity_level: Optional[str] = "Warning"
    symptoms: Optional[str] = None
    causes: Optional[str] = None
    prevention: Optional[str] = None
    pesticide_recommendations: Optional[str] = None
    organic_treatment: Optional[str] = None
    irrigation_recommendations: Optional[str] = None
    fertilizer_recommendations: Optional[str] = None
    recovery_steps: Optional[str] = None
    estimated_recovery_time: Optional[str] = None
    weather_risk: Optional[str] = None
    prevention_tips: Optional[str] = None
    detected_object: Optional[str] = None
    rejection_reason: Optional[str] = None
    health_score: Optional[int] = None
    yield_impact: Optional[str] = None
    pro_tips: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ─── Weather ──────────────────────────────────────────────────────────────────
class WeatherAlert(BaseModel):
    type: str
    severity: str
    message: str
    icon: str

class WeatherForecastDay(BaseModel):
    day: str
    temp: int
    condition: str
    icon: str

class WeatherResponse(BaseModel):
    temp: float
    feels_like: Optional[float] = None
    condition: str
    humidity: int
    wind: float
    uv_index: Optional[float] = None
    rain_probability: Optional[int] = None
    pressure: Optional[float] = None
    visibility: Optional[float] = None
    location: str
    sunrise: Optional[str] = None
    sunset: Optional[str] = None
    daily_high: Optional[float] = None
    daily_low: Optional[float] = None

    class Config:
        from_attributes = True


# ─── DM / DIRECT MESSAGING SCHEMAS ───

class MessageAttachmentOut(BaseModel):
    id: int
    url: str
    file_type: str = "image"
    created_at: datetime

    class Config:
        from_attributes = True


class MessageReactionOut(BaseModel):
    id: int
    user_id: int
    emoji: str
    created_at: datetime

    class Config:
        from_attributes = True


class MessageOut(BaseModel):
    id: int
    conversation_id: int
    sender_id: int
    sender_name: Optional[str] = None
    sender_avatar: Optional[str] = None
    content: Optional[str] = None
    reply_to_id: Optional[int] = None
    reply_to_content: Optional[str] = None
    reply_to_sender: Optional[str] = None
    is_edited: bool = False
    is_deleted_everyone: bool = False
    created_at: datetime
    updated_at: datetime
    status: str = "sent"  # "sent", "delivered", "seen"
    attachments: List[MessageAttachmentOut] = []
    reactions: List[MessageReactionOut] = []

    class Config:
        from_attributes = True


class ConversationParticipantOut(BaseModel):
    id: int
    user_id: int
    full_name: Optional[str] = None
    username: Optional[str] = None
    profile_picture: Optional[str] = None
    is_verified: bool = False
    is_online: bool = False
    last_seen: Optional[datetime] = None
    is_pinned: bool = False
    is_muted: bool = False
    is_archived: bool = False

    class Config:
        from_attributes = True


class ConversationOut(BaseModel):
    id: int
    type: str = "direct"
    title: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    other_participant: Optional[ConversationParticipantOut] = None
    last_message: Optional[MessageOut] = None
    unread_count: int = 0
    is_pinned: bool = False
    is_muted: bool = False
    is_archived: bool = False

    class Config:
        from_attributes = True


class MessageCreate(BaseModel):
    conversation_id: Optional[int] = None
    recipient_id: Optional[int] = None
    content: Optional[str] = None
    reply_to_id: Optional[int] = None
    attachments: List[str] = []  # Image URLs


class MessageEdit(BaseModel):
    content: str


class MessageReactionCreate(BaseModel):
    emoji: str  # ❤️ 👍 😂 😍 😮 😢


class StartConversationRequest(BaseModel):
    target_user_id: int


class BlockUserRequest(BaseModel):
    user_id: int


class BlockStatusOut(BaseModel):
    is_blocked: bool
    blocked_by_me: bool
    blocked_by_them: bool
    user_id: int



class UserOnlineStatusOut(BaseModel):
    user_id: int
    is_online: bool
    last_seen: datetime

    class Config:
        from_attributes = True

    soil_moisture: Optional[str] = None
    farming_suitability: Optional[str] = None
    alerts: Optional[List[WeatherAlert]] = []
    forecast: Optional[List[WeatherForecastDay]] = []