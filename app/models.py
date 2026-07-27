from sqlalchemy import Column, Integer, String, ForeignKey, Float, DateTime, Boolean, Text, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import relationship
from .database import Base
from datetime import datetime


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    phone = Column(String, unique=True, index=True, nullable=True)
    full_name = Column(String, nullable=True, index=True)
    username = Column(String, unique=True, index=True, nullable=True)
    hashed_password = Column(String, nullable=True)
    village = Column(String, nullable=True, index=True)
    district = Column(String, nullable=True)
    state = Column(String, nullable=True)
    farm_size = Column(String, nullable=True)  # Changed to String to support "12.5 Ac"
    experience = Column(String, nullable=True) # Added
    crop_specialization = Column(String, nullable=True, index=True) # Added
    crop_types = Column(String, nullable=True)
    profile_picture = Column(String, nullable=True)
    bio = Column(String, nullable=True)
    website = Column(String, nullable=True)
    is_verified = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    posts = relationship("Post", back_populates="user", cascade="all, delete-orphan")
    likes = relationship("Like", back_populates="user", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="user", cascade="all, delete-orphan")
    saved_posts = relationship("SavedPost", back_populates="user", cascade="all, delete-orphan")
    followers = relationship("Follow", foreign_keys="Follow.following_id", back_populates="following")
    following = relationship("Follow", foreign_keys="Follow.follower_id", back_populates="follower")


class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    content = Column(Text)
    image_url = Column(String, nullable=True)
    hashtags = Column(String, nullable=True)
    location = Column(String, nullable=True)
    crop_category = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    images = Column(Text, nullable=True)

    user = relationship("User", back_populates="posts")
    likes = relationship("Like", back_populates="post", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="post", cascade="all, delete-orphan")
    saves = relationship("SavedPost", back_populates="post", cascade="all, delete-orphan")


class Like(Base):
    __tablename__ = "likes"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    post_id = Column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="likes")
    post = relationship("Post", back_populates="likes")


class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    post_id = Column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    content = Column(Text)
    parent_id = Column(Integer, ForeignKey("comments.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="comments")
    post = relationship("Post", back_populates="comments")
    replies = relationship("Comment", back_populates="parent", cascade="all, delete-orphan")
    parent = relationship("Comment", back_populates="replies", remote_side=[id])


class SavedPost(Base):
    __tablename__ = "saved_posts"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    post_id = Column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="saved_posts")
    post = relationship("Post", back_populates="saves")


class Follow(Base):
    __tablename__ = "follows"
    id = Column(Integer, primary_key=True, index=True)
    follower_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    following_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    follower = relationship("User", foreign_keys=[follower_id], back_populates="following")
    following = relationship("User", foreign_keys=[following_id], back_populates="followers")

    __table_args__ = (
        UniqueConstraint('follower_id', 'following_id', name='unique_follower_following'),
        CheckConstraint('follower_id != following_id', name='check_cannot_follow_self'),
    )


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    actor_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    type = Column(String)  # like, comment, follow
    post_id = Column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), nullable=True)
    message = Column(String)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class CropScan(Base):
    __tablename__ = "crop_scans"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    image_url = Column(String)
    disease_name = Column(String)
    confidence = Column(Float)
    symptoms = Column(Text, nullable=True)
    causes = Column(Text, nullable=True)
    prevention = Column(Text, nullable=True)
    pesticide_recommendations = Column(Text, nullable=True)
    organic_treatment = Column(Text, nullable=True)
    irrigation_recommendations = Column(Text, nullable=True)
    fertilizer_recommendations = Column(Text, nullable=True)
    recovery_steps = Column(Text, nullable=True)
    estimated_recovery_time = Column(String, nullable=True)
    severity_level = Column(String, nullable=True)
    health_score = Column(Integer, nullable=True)
    yield_impact = Column(Text, nullable=True)
    pro_tips = Column(Text, nullable=True)
    prevention_tips = Column(Text, nullable=True)
    is_valid_crop = Column(Boolean, default=True)
    detected_object = Column(String, nullable=True)
    rejection_reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)



class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    conversation_id = Column(String, nullable=True)
    message = Column(Text)
    is_ai = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class OTPCode(Base):
    __tablename__ = "otp_codes"
    id = Column(Integer, primary_key=True, index=True)
    email_or_phone = Column(String, index=True)
    otp_code = Column(String)
    expires_at = Column(DateTime)
    verified = Column(Boolean, default=False)
    attempts = Column(Integer, default=0)
    last_sent_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)


# ─── DIRECT MESSAGING (DM) MODELS ───

class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True, index=True)
    type = Column(String, default="direct")  # "direct" or "group"
    title = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    participants = relationship("Participant", back_populates="conversation", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Participant(Base):
    __tablename__ = "participants"
    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    is_pinned = Column(Boolean, default=False)
    is_muted = Column(Boolean, default=False)
    is_archived = Column(Boolean, default=False)
    last_read_at = Column(DateTime, default=datetime.utcnow)
    joined_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="participants")
    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        UniqueConstraint('conversation_id', 'user_id', name='unique_conversation_participant'),
    )


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    content = Column(Text, nullable=True)
    reply_to_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    is_edited = Column(Boolean, default=False)
    is_deleted_everyone = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="messages")
    sender = relationship("User", foreign_keys=[sender_id])
    reply_to = relationship("Message", remote_side=[id])
    attachments = relationship("MessageAttachment", back_populates="message", cascade="all, delete-orphan")
    reactions = relationship("MessageReaction", back_populates="message", cascade="all, delete-orphan")
    reads = relationship("MessageRead", back_populates="message", cascade="all, delete-orphan")


class MessageRead(Base):
    __tablename__ = "message_reads"
    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String, default="seen")  # "sent", "delivered", "seen"
    read_at = Column(DateTime, default=datetime.utcnow)

    message = relationship("Message", back_populates="reads")
    user = relationship("User")

    __table_args__ = (
        UniqueConstraint('message_id', 'user_id', name='unique_message_user_read'),
    )


class MessageReaction(Base):
    __tablename__ = "message_reactions"
    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    emoji = Column(String, nullable=False)  # ❤️ 👍 😂 😍 😮 😢
    created_at = Column(DateTime, default=datetime.utcnow)

    message = relationship("Message", back_populates="reactions")
    user = relationship("User")

    __table_args__ = (
        UniqueConstraint('message_id', 'user_id', 'emoji', name='unique_message_user_emoji'),
    )


class MessageAttachment(Base):
    __tablename__ = "message_attachments"
    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True)
    url = Column(String, nullable=False)
    file_type = Column(String, default="image")
    created_at = Column(DateTime, default=datetime.utcnow)

    message = relationship("Message", back_populates="attachments")


class MessageDeletedForUser(Base):
    __tablename__ = "message_deleted_for_users"
    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('message_id', 'user_id', name='unique_message_deleted_user'),
    )


class BlockedUser(Base):
    __tablename__ = "blocked_users"
    id = Column(Integer, primary_key=True, index=True)
    blocker_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    blocked_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    blocker = relationship("User", foreign_keys=[blocker_id])
    blocked = relationship("User", foreign_keys=[blocked_id])

    @property
    def blocked_user_id(self):
        return self.blocked_id

    __table_args__ = (
        UniqueConstraint('blocker_id', 'blocked_id', name='unique_blocker_blocked'),
        CheckConstraint('blocker_id != blocked_id', name='check_cannot_block_self'),
    )



class UserOnlineStatus(Base):
    __tablename__ = "user_online_status"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    is_online = Column(Boolean, default=False)
    last_seen = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")

