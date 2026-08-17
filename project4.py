import json
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime, ForeignKey
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship

# ----------------- CONFIGURATION & SECURITY -----------------
SECRET_KEY = "blog-platform-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24
DATABASE_URL = "sqlite:///./blog.db"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

# ----------------- DATABASE MODELS -----------------
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    posts = relationship("Post", back_populates="author", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="author", cascade="all, delete-orphan")


class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    summary = Column(String(300), default="")
    cover_image = Column(String, default="https://images.unsplash.com/photo-1499750310107-5fef28a66643?w=800&q=80")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    author = relationship("User", back_populates="posts")
    comments = relationship("Comment", back_populates="post", cascade="all, delete-orphan", order_by="desc(Comment.created_at)")


class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=False)

    author = relationship("User", back_populates="comments")
    post = relationship("Post", back_populates="comments")


Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ----------------- PYDANTIC SCHEMAS -----------------
class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6)


class UserOut(BaseModel):
    id: int
    username: str

    class Config:
        orm_mode = True


class CommentCreate(BaseModel):
    content: str = Field(..., min_length=1)


class CommentOut(BaseModel):
    id: int
    content: str
    created_at: datetime
    author: UserOut

    class Config:
        orm_mode = True


class PostCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=200)
    summary: Optional[str] = ""
    content: str = Field(..., min_length=10)
    cover_image: Optional[str] = "https://images.unsplash.com/photo-1499750310107-5fef28a66643?w=800&q=80"


class PostUpdate(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    content: Optional[str] = None
    cover_image: Optional[str] = None


class PostListOut(BaseModel):
    id: int
    title: str
    summary: str
    cover_image: str
    created_at: datetime
    author: UserOut
    comment_count: int

    class Config:
        orm_mode = True


class PostDetailOut(BaseModel):
    id: int
    title: str
    summary: str
    content: str
    cover_image: str
    created_at: datetime
    updated_at: datetime
    author: UserOut
    comments: List[CommentOut] = []

    class Config:
        orm_mode = True


# ----------------- AUTH HELPERS -----------------
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    return user


# ----------------- FASTAPI APP & DATABASE SEEDING -----------------
app = FastAPI(title="Full-Stack Blog Engine")


@app.on_event("startup")
def seed_blog_database():
    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            alice = User(username="alice", hashed_password=get_password_hash("password123"))
            bob = User(username="bob", hashed_password=get_password_hash("password123"))
            db.add_all([alice, bob])
            db.commit()
            db.refresh(alice)
            db.refresh(bob)

            post1 = Post(
                title="Architecting Scalable Microservices with FastAPI",
                summary="A practical guide to designing high-throughput Python backends using async routing and dependency injection.",
                content="FastAPI has rapidly become the standard choice for modern Python web applications. Its type hints, automatic schema generation, and high performance enable engineering teams to build clean architectures without sacrificing developer velocity.\n\nWhen scaling APIs, decoupling relational models from request validation schemas using Pydantic ensures clean boundary separation and predictable contracts across services.",
                cover_image="https://images.unsplash.com/photo-1518770660439-4636190af475?w=800&q=80",
                user_id=alice.id,
            )
            post2 = Post(
                title="Designing State-Driven Interfaces with Vanilla JS",
                summary="How to construct reactive client-side Single Page Applications without bulky framework overhead.",
                content="Modern browsers provide native DOM APIs capable of handling dynamic state management smoothly. By relying on clean view routing and modular event handlers, single-page web applications can remain light, fast, and remarkably maintainable.",
                cover_image="https://images.unsplash.com/photo-1555066931-4365d14bab8c?w=800&q=80",
                user_id=bob.id,
            )
            db.add_all([post1, post2])
            db.commit()
            db.refresh(post1)

            comment = Comment(
                content="Excellent architectural breakdown! The focus on dependency injection makes testing straightforward.",
                user_id=bob.id,
                post_id=post1.id,
            )
            db.add(comment)
            db.commit()
    finally:
        db.close()


# ----------------- AUTHENTICATION ROUTES -----------------
@app.post("/api/auth/register", status_code=status.HTTP_201_CREATED)
def register(user_in: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == user_in.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")
    user = User(
        username=user_in.username,
        hashed_password=get_password_hash(user_in.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"message": "Account created successfully"}


@app.post("/api/auth/token")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(
        data={"sub": user.username},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return {"access_token": token, "token_type": "bearer", "username": user.username, "user_id": user.id}


# ----------------- BLOG POST ROUTES -----------------
@app.get("/api/posts", response_model=List[PostListOut])
def list_posts(db: Session = Depends(get_db)):
    posts = db.query(Post).order_by(Post.id.desc()).all()
    results = []
    for p in posts:
        results.append(
            PostListOut(
                id=p.id,
                title=p.title,
                summary=p.summary or (p.content[:140] + "..."),
                cover_image=p.cover_image,
                created_at=p.created_at,
                author=UserOut(id=p.author.id, username=p.author.username),
                comment_count=len(p.comments),
            )
        )
    return results


@app.get("/api/posts/{post_id}", response_model=PostDetailOut)
def get_post(post_id: int, db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


@app.post("/api/posts", response_model=PostDetailOut, status_code=status.HTTP_201_CREATED)
def create_post(
    post_in: PostCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post = Post(
        title=post_in.title,
        summary=post_in.summary or (post_in.content[:140] + "..."),
        content=post_in.content,
        cover_image=post_in.cover_image or "https://images.unsplash.com/photo-1499750310107-5fef28a66643?w=800&q=80",
        user_id=current_user.id,
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


@app.put("/api/posts/{post_id}", response_model=PostDetailOut)
def update_post(
    post_id: int,
    post_in: PostUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    if post.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to edit this post")

    if post_in.title is not None:
        post.title = post_in.title
    if post_in.summary is not None:
        post.summary = post_in.summary
    if post_in.content is not None:
        post.content = post_in.content
    if post_in.cover_image is not None:
        post.cover_image = post_in.cover_image

    post.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(post)
    return post


@app.delete("/api/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_post(
    post_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    if post.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this post")

    db.delete(post)
    db.commit()
    return None


# ----------------- COMMENT ROUTES -----------------
@app.post("/api/posts/{post_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
def create_comment(
    post_id: int,
    comment_in: CommentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    comment = Comment(
        content=comment_in.content,
        user_id=current_user.id,
        post_id=post.id,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


@app.delete("/api/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(
    comment_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    if comment.user_id != current_user.id and comment.post.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this comment")

    db.delete(comment)
    db.commit()
    return None


# ----------------- EMBEDDED FRONTEND (HTML/JS/TAILWIND) -----------------
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>InkFlow - Modern Engineering Blog</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen flex flex-col font-sans selection:bg-indigo-500 selection:text-white">

  <!-- Header / Navigation -->
  <header class="sticky top-0 z-50 bg-slate-900/90 backdrop-blur border-b border-slate-800">
    <div class="max-w-5xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
      <div class="flex items-center gap-3 cursor-pointer" onclick="navigate('feed')">
        <div class="bg-indigo-600 p-2 rounded-xl text-white shadow-lg shadow-indigo-500/30">
          <i class="fa-solid fa-feather text-lg"></i>
        </div>
        <span class="text-xl font-bold tracking-tight text-white">Ink<span class="text-indigo-400">Flow</span></span>
      </div>

      <div class="flex items-center gap-4">
        <button onclick="navigate('feed')" class="text-slate-300 hover:text-white text-sm font-medium transition">Articles</button>
        <button id="nav-write" onclick="openPostEditor()" class="hidden bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold px-3.5 py-2 rounded-lg transition flex items-center gap-2 shadow-lg shadow-indigo-600/20">
          <i class="fa-solid fa-pen-nib"></i> Write Post
        </button>

        <div id="auth-actions" class="flex items-center gap-2 pl-2 border-l border-slate-800">
          <button onclick="navigate('auth')" class="bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold px-3.5 py-2 rounded-lg transition">Sign In</button>
        </div>

        <div id="user-profile" class="hidden flex items-center gap-3 pl-2 border-l border-slate-800">
          <span id="user-badge" class="text-xs font-medium text-slate-300 bg-slate-800 px-3 py-1.5 rounded-full border border-slate-700"></span>
          <button onclick="logout()" class="text-slate-400 hover:text-rose-400 text-sm transition" title="Sign Out">
            <i class="fa-solid fa-arrow-right-from-bracket"></i>
          </button>
        </div>
      </div>
    </div>
  </header>

  <!-- Main View Container -->
  <main class="flex-1 max-w-5xl w-full mx-auto px-4 sm:px-6 py-8">
    
    <!-- Toast Notification -->
    <div id="toast" class="fixed bottom-5 right-5 z-50 transform transition-all duration-300 translate-y-20 opacity-0 bg-slate-900 border border-slate-700 text-slate-100 px-4 py-3 rounded-xl shadow-2xl flex items-center gap-3">
      <i id="toast-icon" class="fa-solid fa-circle-check text-emerald-400"></i>
      <span id="toast-msg" class="text-sm font-medium">Notification</span>
    </div>

    <!-- VIEW: Feed (List of Posts) -->
    <section id="view-feed" class="space-y-6">
      <div class="flex justify-between items-center pb-4 border-b border-slate-800">
        <div>
          <h1 class="text-2xl font-bold tracking-tight text-white">Latest Publications</h1>
          <p class="text-slate-400 text-sm">Deep dives into software architecture, design, and engineering.</p>
        </div>
      </div>
      <div id="posts-grid" class="grid grid-cols-1 md:grid-cols-2 gap-6"></div>
    </section>

    <!-- VIEW: Post Detail & Comments -->
    <section id="view-post" class="hidden max-w-3xl mx-auto space-y-8">
      <button onclick="navigate('feed')" class="text-xs font-semibold text-slate-400 hover:text-white flex items-center gap-2 transition">
        <i class="fa-solid fa-arrow-left"></i> Back to feed
      </button>

      <article class="bg-slate-900/50 border border-slate-800/80 rounded-2xl overflow-hidden shadow-2xl">
        <img id="post-detail-cover" class="w-full h-64 sm:h-80 object-cover" src="" alt="Cover">
        <div class="p-6 sm:p-8 space-y-6">
          <div class="flex items-center justify-between text-xs text-slate-400">
            <span id="post-detail-author" class="font-semibold text-indigo-400"></span>
            <span id="post-detail-date"></span>
          </div>
          
          <h1 id="post-detail-title" class="text-2xl sm:text-3xl font-extrabold text-white tracking-tight leading-snug"></h1>
          <p id="post-detail-summary" class="text-slate-400 text-sm italic border-l-2 border-indigo-500 pl-3"></p>
          
          <div id="post-detail-content" class="text-slate-300 text-sm sm:text-base leading-relaxed whitespace-pre-wrap pt-4 border-t border-slate-800"></div>

          <!-- Post Author Controls -->
          <div id="post-owner-actions" class="hidden flex gap-3 pt-6 border-t border-slate-800">
            <button onclick="editCurrentPost()" class="text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 px-4 py-2 rounded-lg transition flex items-center gap-1.5">
              <i class="fa-solid fa-pen"></i> Edit Article
            </button>
            <button onclick="deleteCurrentPost()" class="text-xs font-semibold bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/20 px-4 py-2 rounded-lg transition flex items-center gap-1.5">
              <i class="fa-solid fa-trash"></i> Delete
            </button>
          </div>
        </div>
      </article>

      <!-- Comments Section -->
      <section class="space-y-6 pt-4">
        <div class="flex items-center justify-between">
          <h2 class="text-xl font-bold text-white flex items-center gap-2">
            <span>Comments</span>
            <span id="post-comment-badge" class="text-xs font-semibold bg-slate-800 text-indigo-400 px-2 py-0.5 rounded-full border border-slate-700">0</span>
          </h2>
        </div>

        <!-- Add Comment Form -->
        <div id="comment-form-container" class="bg-slate-900/80 border border-slate-800 p-4 rounded-xl space-y-3">
          <textarea id="comment-input" rows="3" placeholder="Share your perspective..." class="w-full bg-slate-950 border border-slate-800 rounded-lg p-3 text-sm text-white focus:outline-none focus:border-indigo-500 resize-none"></textarea>
          <div class="flex justify-end">
            <button onclick="handleAddComment()" class="bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold px-4 py-2 rounded-lg transition shadow-md shadow-indigo-600/20">
              Publish Comment
            </button>
          </div>
        </div>

        <!-- Comments List -->
        <div id="comments-container" class="space-y-3"></div>
      </section>
    </section>

    <!-- VIEW: Create / Edit Post Modal -->
    <section id="view-editor" class="hidden max-w-2xl mx-auto space-y-6">
      <div class="flex justify-between items-center">
        <h1 id="editor-heading" class="text-2xl font-bold text-white">Create New Article</h1>
        <button onclick="navigate('feed')" class="text-slate-400 hover:text-white text-sm"><i class="fa-solid fa-xmark"></i> Cancel</button>
      </div>

      <form onsubmit="handleSavePost(event)" class="bg-slate-900/80 border border-slate-800 p-6 sm:p-8 rounded-2xl space-y-4 shadow-xl">
        <input type="hidden" id="editor-post-id" value="">
        <div>
          <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Article Title</label>
          <input type="text" id="editor-title" required class="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500">
        </div>
        <div>
          <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Summary (Short Abstract)</label>
          <input type="text" id="editor-summary" class="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500">
        </div>
        <div>
          <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Cover Image URL (Optional)</label>
          <input type="url" id="editor-cover" placeholder="https://images.unsplash.com/..." class="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500">
        </div>
        <div>
          <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Content (Markdown Supported)</label>
          <textarea id="editor-content" rows="10" required class="w-full bg-slate-950 border border-slate-800 rounded-lg p-3 text-sm text-white focus:outline-none focus:border-indigo-500 resize-y"></textarea>
        </div>
        <div class="flex justify-end gap-3 pt-2">
          <button type="button" onclick="navigate('feed')" class="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-xs font-semibold rounded-lg text-slate-300 transition">Cancel</button>
          <button type="submit" id="editor-submit-btn" class="px-5 py-2 bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold rounded-lg text-white transition shadow-lg shadow-indigo-600/30">Publish Article</button>
        </div>
      </form>
    </section>

    <!-- VIEW: Authentication -->
    <section id="view-auth" class="hidden max-w-md mx-auto mt-10">
      <div class="bg-slate-900/90 border border-slate-800 p-8 rounded-2xl shadow-2xl">
        <div class="flex gap-4 border-b border-slate-800 pb-3 mb-6">
          <button id="tab-login" onclick="setAuthMode('login')" class="font-semibold text-indigo-400 border-b-2 border-indigo-400 pb-2 flex-1">Sign In</button>
          <button id="tab-register" onclick="setAuthMode('register')" class="font-semibold text-slate-500 pb-2 flex-1">Register</button>
        </div>

        <form onsubmit="handleAuth(event)" class="space-y-4">
          <div>
            <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Username</label>
            <input type="text" id="auth-username" required class="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-indigo-500">
          </div>
          <div>
            <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Password</label>
            <input type="password" id="auth-password" required class="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-indigo-500">
          </div>
          <button type="submit" id="auth-submit-btn" class="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-medium py-2.5 rounded-lg transition shadow-lg shadow-indigo-600/30 text-sm">Sign In</button>
        </form>

        <div class="mt-6 pt-4 border-t border-slate-800 text-xs text-slate-500 space-y-1">
          <p><strong>Demo Account 1:</strong> alice / password123</p>
          <p><strong>Demo Account 2:</strong> bob / password123</p>
        </div>
      </div>
    </section>

  </main>

  <script>
    let token = localStorage.getItem("token");
    let username = localStorage.getItem("username");
    let currentUserId = parseInt(localStorage.getItem("user_id") || "0");
    let currentPostCache = null;
    let authMode = "login";

    function showToast(msg, isError = false) {
      const toast = document.getElementById("toast");
      const toastMsg = document.getElementById("toast-msg");
      const toastIcon = document.getElementById("toast-icon");
      toastMsg.innerText = msg;
      toastIcon.className = isError ? "fa-solid fa-circle-exclamation text-rose-400" : "fa-solid fa-circle-check text-emerald-400";
      toast.classList.remove("translate-y-20", "opacity-0");
      setTimeout(() => toast.classList.add("translate-y-20", "opacity-0"), 3500);
    }

    function updateAuthState() {
      const authActions = document.getElementById("auth-actions");
      const userProfile = document.getElementById("user-profile");
      const navWrite = document.getElementById("nav-write");
      const userBadge = document.getElementById("user-badge");

      if (token && username) {
        authActions.classList.add("hidden");
        userProfile.classList.remove("hidden");
        navWrite.classList.remove("hidden");
        userBadge.innerText = `@${username}`;
      } else {
        authActions.classList.remove("hidden");
        userProfile.classList.add("hidden");
        navWrite.classList.add("hidden");
      }
    }

    function navigate(viewName) {
      ["feed", "post", "editor", "auth"].forEach(v => {
        document.getElementById(`view-${v}`).classList.add("hidden");
      });
      document.getElementById(`view-${viewName}`).classList.remove("hidden");

      if (viewName === "feed") fetchPosts();
    }

    function setAuthMode(mode) {
      authMode = mode;
      const tabLogin = document.getElementById("tab-login");
      const tabRegister = document.getElementById("tab-register");
      const btn = document.getElementById("auth-submit-btn");

      if (mode === "login") {
        tabLogin.className = "font-semibold text-indigo-400 border-b-2 border-indigo-400 pb-2 flex-1";
        tabRegister.className = "font-semibold text-slate-500 pb-2 flex-1";
        btn.innerText = "Sign In";
      } else {
        tabRegister.className = "font-semibold text-indigo-400 border-b-2 border-indigo-400 pb-2 flex-1";
        tabLogin.className = "font-semibold text-slate-500 pb-2 flex-1";
        btn.innerText = "Create Account";
      }
    }

    async function handleAuth(e) {
      e.preventDefault();
      const u = document.getElementById("auth-username").value.trim();
      const p = document.getElementById("auth-password").value.trim();

      try {
        if (authMode === "register") {
          const res = await fetch("/api/auth/register", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({username: u, password: p})
          });
          if (!res.ok) {
            const data = await res.json();
            throw new Error(data.detail || "Registration failed");
          }
          showToast("Account created! Signing you in...");
        }

        const formData = new URLSearchParams();
        formData.append("username", u);
        formData.append("password", p);

        const res = await fetch("/api/auth/token", {
          method: "POST",
          headers: {"Content-Type": "application/x-www-form-urlencoded"},
          body: formData
        });

        if (!res.ok) throw new Error("Invalid username or password");
        const data = await res.json();
        
        token = data.access_token;
        username = data.username;
        currentUserId = data.user_id;

        localStorage.setItem("token", token);
        localStorage.setItem("username", username);
        localStorage.setItem("user_id", currentUserId);

        updateAuthState();
        showToast(`Welcome back, ${username}!`);
        navigate("feed");
      } catch (err) {
        showToast(err.message, true);
      }
    }

    function logout() {
      token = null;
      username = null;
      currentUserId = 0;
      localStorage.clear();
      updateAuthState();
      showToast("Logged out successfully");
      navigate("feed");
    }

    // Post Feed
    async function fetchPosts() {
      try {
        const res = await fetch("/api/posts");
        const posts = await res.json();
        renderFeed(posts);
      } catch (err) {
        showToast("Failed loading articles", true);
      }
    }

    function renderFeed(posts) {
      const container = document.getElementById("posts-grid");
      if (!posts.length) {
        container.innerHTML = `<div class="col-span-full text-center py-12 text-slate-500 text-sm">No articles published yet. Be the first to share your thoughts!</div>`;
        return;
      }

      container.innerHTML = posts.map(p => `
        <div onclick="viewPostDetail(${p.id})" class="bg-slate-900/60 border border-slate-800 hover:border-indigo-500/40 rounded-2xl overflow-hidden cursor-pointer group flex flex-col justify-between transition-all duration-300 hover:shadow-xl hover:shadow-indigo-500/5">
          <div>
            <div class="aspect-video w-full overflow-hidden bg-slate-950">
              <img src="${p.cover_image}" alt="${p.title}" class="w-full h-full object-cover group-hover:scale-105 transition duration-500">
            </div>
            <div class="p-5 space-y-2.5">
              <div class="flex items-center justify-between text-xs text-slate-400">
                <span class="text-indigo-400 font-medium">@${p.author.username}</span>
                <span>${new Date(p.created_at).toLocaleDateString()}</span>
              </div>
              <h3 class="font-bold text-lg text-white group-hover:text-indigo-300 transition line-clamp-2">${p.title}</h3>
              <p class="text-xs text-slate-400 line-clamp-3 leading-relaxed">${p.summary}</p>
            </div>
          </div>
          <div class="px-5 py-3.5 border-t border-slate-800/80 flex items-center justify-between text-xs text-slate-500">
            <span class="flex items-center gap-1.5"><i class="fa-regular fa-comment"></i> ${p.comment_count} comments</span>
            <span class="text-indigo-400 font-medium group-hover:translate-x-1 transition duration-200">Read article &rarr;</span>
          </div>
        </div>
      `).join("");
    }

    // Post Detail & Comments
    async function viewPostDetail(postId) {
      try {
        const res = await fetch(`/api/posts/${postId}`);
        if (!res.ok) throw new Error("Article not found");
        currentPostCache = await res.json();

        document.getElementById("post-detail-cover").src = currentPostCache.cover_image;
        document.getElementById("post-detail-title").innerText = currentPostCache.title;
        document.getElementById("post-detail-summary").innerText = currentPostCache.summary || "";
        document.getElementById("post-detail-content").innerText = currentPostCache.content;
        document.getElementById("post-detail-author").innerText = `By @${currentPostCache.author.username}`;
        document.getElementById("post-detail-date").innerText = `Published ${new Date(currentPostCache.created_at).toLocaleDateString()}`;

        // Owner Controls
        const ownerActions = document.getElementById("post-owner-actions");
        if (token && currentPostCache.author.id === currentUserId) {
          ownerActions.classList.remove("hidden");
        } else {
          ownerActions.classList.add("hidden");
        }

        renderComments(currentPostCache.comments);
        navigate("post");
      } catch (err) {
        showToast(err.message, true);
      }
    }

    function renderComments(comments) {
      const container = document.getElementById("comments-container");
      document.getElementById("post-comment-badge").innerText = comments.length;

      if (!comments.length) {
        container.innerHTML = `<p class="text-slate-500 text-xs py-4 text-center">No comments yet. Join the conversation!</p>`;
        return;
      }

      container.innerHTML = comments.map(c => `
        <div class="bg-slate-900/60 border border-slate-800/80 p-4 rounded-xl space-y-2">
          <div class="flex items-center justify-between text-xs">
            <span class="font-semibold text-indigo-400">@${c.author.username}</span>
            <div class="flex items-center gap-3">
              <span class="text-slate-500">${new Date(c.created_at).toLocaleDateString()}</span>
              ${(token && (c.author.id === currentUserId || currentPostCache.author.id === currentUserId)) ? `
                <button onclick="deleteCommentItem(${c.id})" class="text-slate-500 hover:text-rose-400 transition" title="Delete Comment">
                  <i class="fa-solid fa-trash-can text-xs"></i>
                </button>
              ` : ''}
            </div>
          </div>
          <p class="text-sm text-slate-300 whitespace-pre-wrap">${c.content}</p>
        </div>
      `).join("");
    }

    async function handleAddComment() {
      if (!token) {
        showToast("Please sign in to comment", true);
        return navigate("auth");
      }

      const input = document.getElementById("comment-input");
      const content = input.value.trim();
      if (!content) return showToast("Comment cannot be empty", true);

      try {
        const res = await fetch(`/api/posts/${currentPostCache.id}/comments`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${token}`
          },
          body: JSON.stringify({ content })
        });

        if (!res.ok) throw new Error("Failed to post comment");
        input.value = "";
        showToast("Comment published!");
        viewPostDetail(currentPostCache.id);
      } catch (err) {
        showToast(err.message, true);
      }
    }

    async function deleteCommentItem(commentId) {
      if (!confirm("Are you sure you want to remove this comment?")) return;
      try {
        const res = await fetch(`/api/comments/${commentId}`, {
          method: "DELETE",
          headers: { "Authorization": `Bearer ${token}` }
        });
        if (!res.ok) throw new Error("Could not delete comment");
        showToast("Comment removed");
        viewPostDetail(currentPostCache.id);
      } catch (err) {
        showToast(err.message, true);
      }
    }

    // Post Creation & Editing
    function openPostEditor(post = null) {
      if (!token) return navigate("auth");
      
      document.getElementById("editor-post-id").value = post ? post.id : "";
      document.getElementById("editor-heading").innerText = post ? "Edit Article" : "Create New Article";
      document.getElementById("editor-submit-btn").innerText = post ? "Update Article" : "Publish Article";
      document.getElementById("editor-title").value = post ? post.title : "";
      document.getElementById("editor-summary").value = post ? post.summary : "";
      document.getElementById("editor-cover").value = post ? post.cover_image : "";
      document.getElementById("editor-content").value = post ? post.content : "";

      navigate("editor");
    }

    function editCurrentPost() {
      if (!currentPostCache) return;
      openPostEditor(currentPostCache);
    }

    async function handleSavePost(e) {
      e.preventDefault();
      const postId = document.getElementById("editor-post-id").value;
      const payload = {
        title: document.getElementById("editor-title").value.trim(),
        summary: document.getElementById("editor-summary").value.trim(),
        cover_image: document.getElementById("editor-cover").value.trim() || undefined,
        content: document.getElementById("editor-content").value.trim()
      };

      try {
        const url = postId ? `/api/posts/${postId}` : "/api/posts";
        const method = postId ? "PUT" : "POST";

        const res = await fetch(url, {
          method: method,
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${token}`
          },
          body: JSON.stringify(payload)
        });

        if (!res.ok) throw new Error("Failed to save article");
        const savedPost = await res.json();
        showToast(postId ? "Article updated!" : "Article published!");
        viewPostDetail(savedPost.id);
      } catch (err) {
        showToast(err.message, true);
      }
    }

    async function deleteCurrentPost() {
      if (!confirm("Are you sure you want to permanently delete this article?")) return;
      try {
        const res = await fetch(`/api/posts/${currentPostCache.id}`, {
          method: "DELETE",
          headers: { "Authorization": `Bearer ${token}` }
        });
        if (!res.ok) throw new Error("Could not delete article");
        showToast("Article deleted successfully");
        navigate("feed");
      } catch (err) {
        showToast(err.message, true);
      }
    }

    // App Initialization
    updateAuthState();
    fetchPosts();
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def serve_index():
    return HTML_CONTENT


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)