import json
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship

# ----------------- CONFIGURATION & CONSTANTS -----------------
SECRET_KEY = "super-secret-task-manager-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24
DATABASE_URL = "sqlite:///./tasks.db"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

# ----------------- DATABASE SETUP -----------------
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class UserModel(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    tasks = relationship("TaskModel", back_populates="owner")


class TaskModel(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String, default="")
    completed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    user_id = Column(Integer, ForeignKey("users.id"))
    owner = relationship("UserModel", back_populates="tasks")


Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ----------------- SCHEMAS -----------------
class UserCreate(BaseModel):
    username: str
    password: str


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = ""


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    completed: Optional[bool] = None


class TaskResponse(BaseModel):
    id: int
    title: str
    description: str
    completed: bool
    created_at: datetime
    user_id: int

    class Config:
        orm_mode = True


# ----------------- WEBSOCKET CONNECTION MANAGER -----------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except Exception:
                pass


ws_manager = ConnectionManager()

# ----------------- AUTHENTICATION HELPERS -----------------
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(UserModel).filter(UserModel.username == username).first()
    if user is None:
        raise credentials_exception
    return user


# ----------------- FASTAPI APP & ROUTES -----------------
app = FastAPI(title="Real-Time Task Manager")


@app.post("/api/auth/register", status_code=status.HTTP_201_CREATED)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(UserModel).filter(UserModel.username == user_data.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already registered")
    user = UserModel(
        username=user_data.username,
        hashed_password=get_password_hash(user_data.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"message": "User registered successfully"}


@app.post("/api/auth/token")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(UserModel).filter(UserModel.username == form_data.username).first()
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
    return {"access_token": token, "token_type": "bearer"}


@app.get("/api/tasks", response_model=List[TaskResponse])
def list_tasks(current_user: UserModel = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(TaskModel).filter(TaskModel.user_id == current_user.id).order_by(TaskModel.id.desc()).all()


@app.post("/api/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    task_in: TaskCreate,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = TaskModel(
        title=task_in.title,
        description=task_in.description or "",
        user_id=current_user.id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    await ws_manager.broadcast({"action": "create", "task_id": task.id, "user_id": current_user.id})
    return task


@app.put("/api/tasks/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: int,
    task_in: TaskUpdate,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = db.query(TaskModel).filter(TaskModel.id == task_id, TaskModel.user_id == current_user.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task_in.title is not None:
        task.title = task_in.title
    if task_in.description is not None:
        task.description = task_in.description
    if task_in.completed is not None:
        task.completed = task_in.completed

    db.commit()
    db.refresh(task)

    await ws_manager.broadcast({"action": "update", "task_id": task.id, "user_id": current_user.id})
    return task


@app.delete("/api/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = db.query(TaskModel).filter(TaskModel.id == task_id, TaskModel.user_id == current_user.id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    db.delete(task)
    db.commit()

    await ws_manager.broadcast({"action": "delete", "task_id": task_id, "user_id": current_user.id})
    return None


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


# ----------------- EMBEDDED FRONTEND (HTML + JS + Tailwind CSS) -----------------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Task Manager</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-900 text-slate-100 min-h-screen flex flex-col items-center p-4">
  <div class="w-full max-w-2xl">
    <!-- Header -->
    <header class="flex justify-between items-center py-6 border-b border-slate-800">
      <h1 class="text-2xl font-bold tracking-tight text-indigo-400">⚡ Task Flow</h1>
      <div id="user-section" class="hidden flex items-center gap-3">
        <span id="user-display" class="text-sm font-medium text-slate-400"></span>
        <button onclick="logout()" class="text-xs bg-slate-800 hover:bg-slate-700 px-3 py-1.5 rounded transition">Logout</button>
      </div>
    </header>

    <!-- Auth View -->
    <div id="auth-box" class="mt-12 bg-slate-800/60 p-6 sm:p-8 rounded-xl border border-slate-700 shadow-xl">
      <div class="flex gap-4 border-b border-slate-700 pb-3 mb-6">
        <button id="tab-login" onclick="toggleAuthTab('login')" class="font-semibold text-indigo-400 border-b-2 border-indigo-400 pb-2">Login</button>
        <button id="tab-register" onclick="toggleAuthTab('register')" class="font-semibold text-slate-400 pb-2">Register</button>
      </div>
      <form id="auth-form" onsubmit="handleAuth(event)" class="space-y-4">
        <div>
          <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Username</label>
          <input type="text" id="username" required class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-white focus:outline-none focus:border-indigo-500">
        </div>
        <div>
          <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Password</label>
          <input type="password" id="password" required class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-white focus:outline-none focus:border-indigo-500">
        </div>
        <p id="auth-error" class="text-red-400 text-xs hidden"></p>
        <button type="submit" id="auth-submit" class="w-full bg-indigo-600 hover:bg-indigo-500 font-semibold py-2 rounded transition">Login</button>
      </form>
    </div>

    <!-- App Dashboard View -->
    <div id="app-box" class="hidden mt-8 space-y-6">
      <!-- Create Task -->
      <form onsubmit="handleCreateTask(event)" class="bg-slate-800/40 p-4 rounded-xl border border-slate-700 space-y-3">
        <input type="text" id="task-title" placeholder="What needs to be done?" required class="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-white text-sm focus:outline-none focus:border-indigo-500">
        <div class="flex gap-2">
          <input type="text" id="task-desc" placeholder="Details/notes (optional)" class="flex-1 bg-slate-900 border border-slate-700 rounded px-3 py-2 text-white text-xs focus:outline-none focus:border-indigo-500">
          <button type="submit" class="bg-indigo-600 hover:bg-indigo-500 px-5 py-2 rounded text-xs font-semibold transition">Add Task</button>
        </div>
      </form>

      <!-- Task List Stats & Filter -->
      <div class="flex justify-between items-center text-xs text-slate-400">
        <span id="task-count">0 tasks</span>
        <div class="flex items-center gap-1.5">
          <span class="w-2 h-2 rounded-full bg-emerald-500 inline-block animate-pulse"></span>
          <span>Live Synced</span>
        </div>
      </div>

      <!-- Task Items List -->
      <div id="task-list" class="space-y-2"></div>
    </div>
  </div>

  <script>
    let token = localStorage.getItem("token");
    let currentUser = localStorage.getItem("username");
    let currentAuthMode = "login";
    let ws = null;

    function toggleAuthTab(mode) {
      currentAuthMode = mode;
      const tabLogin = document.getElementById("tab-login");
      const tabRegister = document.getElementById("tab-register");
      const btn = document.getElementById("auth-submit");
      document.getElementById("auth-error").classList.add("hidden");

      if (mode === "login") {
        tabLogin.className = "font-semibold text-indigo-400 border-b-2 border-indigo-400 pb-2";
        tabRegister.className = "font-semibold text-slate-400 pb-2";
        btn.innerText = "Login";
      } else {
        tabRegister.className = "font-semibold text-indigo-400 border-b-2 border-indigo-400 pb-2";
        tabLogin.className = "font-semibold text-slate-400 pb-2";
        btn.innerText = "Create Account";
      }
    }

    async function handleAuth(e) {
      e.preventDefault();
      const u = document.getElementById("username").value.trim();
      const p = document.getElementById("password").value.trim();
      const err = document.getElementById("auth-error");

      try {
        if (currentAuthMode === "register") {
          const res = await fetch("/api/auth/register", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({username: u, password: p})
          });
          if (!res.ok) {
            const data = await res.json();
            throw new Error(data.detail || "Registration failed");
          }
          toggleAuthTab("login");
          alert("Account created. Please log in.");
          return;
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
        currentUser = u;
        localStorage.setItem("token", token);
        localStorage.setItem("username", currentUser);
        initDashboard();
      } catch (error) {
        err.innerText = error.message;
        err.classList.remove("hidden");
      }
    }

    function logout() {
      token = null;
      currentUser = null;
      localStorage.clear();
      if (ws) ws.close();
      document.getElementById("auth-box").classList.remove("hidden");
      document.getElementById("app-box").classList.add("hidden");
      document.getElementById("user-section").classList.add("hidden");
    }

    function initWebSocket() {
      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      ws = new WebSocket(`${proto}//${location.host}/ws`);
      ws.onmessage = () => {
        if (token) fetchTasks();
      };
    }

    async function fetchTasks() {
      try {
        const res = await fetch("/api/tasks", {
          headers: {"Authorization": `Bearer ${token}`}
        });
        if (res.status === 401) return logout();
        const tasks = await res.json();
        renderTasks(tasks);
      } catch (err) {
        console.error("Failed loading tasks", err);
      }
    }

    function renderTasks(tasks) {
      const container = document.getElementById("task-list");
      document.getElementById("task-count").innerText = `${tasks.length} total tasks`;
      if (!tasks.length) {
        container.innerHTML = `<div class="text-center py-8 text-slate-500 text-sm">No tasks yet. Create one above!</div>`;
        return;
      }
      container.innerHTML = tasks.map(t => `
        <div class="flex items-center justify-between p-3.5 bg-slate-800/80 hover:bg-slate-800 border border-slate-700/60 rounded-lg transition">
          <div class="flex items-start gap-3 flex-1 overflow-hidden pr-2">
            <input type="checkbox" onchange="toggleTask(${t.id}, this.checked)" ${t.completed ? "checked" : ""} class="mt-1 h-4 w-4 rounded border-slate-700 bg-slate-900 text-indigo-600 focus:ring-0 cursor-pointer">
            <div class="truncate">
              <p class="text-sm font-medium ${t.completed ? 'line-through text-slate-500' : 'text-slate-200'} truncate">${t.title}</p>
              ${t.description ? `<p class="text-xs text-slate-400 truncate mt-0.5">${t.description}</p>` : ''}
            </div>
          </div>
          <button onclick="deleteTask(${t.id})" class="text-slate-500 hover:text-rose-400 p-1 transition" title="Delete">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" /></svg>
          </button>
        </div>
      `).join('');
    }

    async function handleCreateTask(e) {
      e.preventDefault();
      const titleInput = document.getElementById("task-title");
      const descInput = document.getElementById("task-desc");
      await fetch("/api/tasks", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({title: titleInput.value, description: descInput.value})
      });
      titleInput.value = "";
      descInput.value = "";
      fetchTasks();
    }

    async function toggleTask(id, completed) {
      await fetch(`/api/tasks/${id}`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({completed})
      });
      fetchTasks();
    }

    async function deleteTask(id) {
      await fetch(`/api/tasks/${id}`, {
        method: "DELETE",
        headers: {"Authorization": `Bearer ${token}`}
      });
      fetchTasks();
    }

    function initDashboard() {
      document.getElementById("auth-box").classList.add("hidden");
      document.getElementById("app-box").classList.remove("hidden");
      document.getElementById("user-section").classList.remove("hidden");
      document.getElementById("user-display").innerText = `@${currentUser}`;
      initWebSocket();
      fetchTasks();
    }

    if (token && currentUser) {
      initDashboard();
    }
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    return HTML_TEMPLATE


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)