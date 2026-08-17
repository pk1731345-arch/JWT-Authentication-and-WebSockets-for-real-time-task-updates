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
    create_engine, Column, Integer, String, Float, ForeignKey, DateTime
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship

# ----------------- CONFIGURATION & CONSTANTS -----------------
SECRET_KEY = "ecommerce-production-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

# Switch to PostgreSQL: "postgresql://user:password@localhost/ecommerce_db"
# Switch to MySQL: "mysql+pymysql://user:password@localhost/ecommerce_db"
DATABASE_URL = "sqlite:///./ecommerce.db"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

# ----------------- DATABASE MODELS -----------------
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="customer")  # "admin" or "customer"
    orders = relationship("Order", back_populates="customer")


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    description = Column(String, default="")
    price = Column(Float, nullable=False)
    stock = Column(Integer, default=0, nullable=False)
    image_url = Column(String, default="https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=500&q=80")


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    total_amount = Column(Float, nullable=False)
    status = Column(String, default="PENDING")  # PENDING, PROCESSING, SHIPPED, DELIVERED
    created_at = Column(DateTime, default=datetime.utcnow)
    
    customer = relationship("User", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    product_name = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)

    order = relationship("Order", back_populates="items")


Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ----------------- PYDANTIC SCHEMAS -----------------
class UserCreate(BaseModel):
    username: str
    password: str
    role: Optional[str] = "customer"


class UserResponse(BaseModel):
    id: int
    username: str
    role: str

    class Config:
        orm_mode = True


class ProductCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    price: float = Field(..., gt=0)
    stock: int = Field(..., ge=0)
    image_url: Optional[str] = "https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=500&q=80"


class ProductResponse(ProductCreate):
    id: int

    class Config:
        orm_mode = True


class CartItemSchema(BaseModel):
    product_id: int
    quantity: int = Field(..., gt=0)


class CheckoutRequest(BaseModel):
    items: List[CartItemSchema]


class OrderItemResponse(BaseModel):
    product_id: int
    product_name: str
    quantity: int
    unit_price: float

    class Config:
        orm_mode = True


class OrderResponse(BaseModel):
    id: int
    user_id: int
    total_amount: float
    status: str
    created_at: datetime
    items: List[OrderItemResponse]

    class Config:
        orm_mode = True


class StatusUpdateSchema(BaseModel):
    status: str


# ----------------- AUTH & SECURITY HELPERS -----------------
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


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required for this action"
        )
    return current_user


# ----------------- FASTAPI APP & DATABASE SEEDING -----------------
app = FastAPI(title="Full-Stack E-Commerce API")


@app.on_event("startup")
def seed_database():
    db = SessionLocal()
    try:
        if not db.query(User).filter(User.username == "admin").first():
            admin = User(username="admin", hashed_password=get_password_hash("adminpassword"), role="admin")
            customer = User(username="customer", hashed_password=get_password_hash("customerpassword"), role="customer")
            db.add_all([admin, customer])

        if db.query(Product).count() == 0:
            sample_products = [
                Product(
                    name="Wireless Noise-Cancelling Headphones",
                    description="High-fidelity audio with active noise cancellation and 30-hour battery life.",
                    price=199.99,
                    stock=15,
                    image_url="https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=500&q=80"
                ),
                Product(
                    name="Minimalist Mechanical Keyboard",
                    description="Customizable hot-swappable RGB mechanical keyboard with tactile switches.",
                    price=89.50,
                    stock=25,
                    image_url="https://images.unsplash.com/photo-1587829741301-dc798b83add3?w=500&q=80"
                ),
                Product(
                    name="Ergonomic Optical Mouse",
                    description="Precision wireless tracking engineered for daily comfort and productivity.",
                    price=49.99,
                    stock=40,
                    image_url="https://images.unsplash.com/photo-1527864550417-7fd91fc51a46?w=500&q=80"
                ),
                Product(
                    name="Ultra-Wide 4K Gaming Monitor",
                    description="34-inch curved display offering vibrant HDR color and 144Hz refresh rate.",
                    price=449.00,
                    stock=8,
                    image_url="https://images.unsplash.com/photo-1527443224154-c4a3942d3acf?w=500&q=80"
                )
            ]
            db.add_all(sample_products)
        db.commit()
    finally:
        db.close()


# ----------------- AUTHENTICATION ROUTES -----------------
@app.post("/api/auth/register", status_code=status.HTTP_201_CREATED)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == user_data.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")
    
    role = user_data.role if user_data.role in ["admin", "customer"] else "customer"
    new_user = User(
        username=user_data.username,
        hashed_password=get_password_hash(user_data.password),
        role=role
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
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
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return {"access_token": token, "token_type": "bearer", "role": user.role, "username": user.username}


@app.get("/api/auth/me", response_model=UserResponse)
def get_user_profile(current_user: User = Depends(get_current_user)):
    return current_user


# ----------------- PRODUCT ROUTES -----------------
@app.get("/api/products", response_model=List[ProductResponse])
def get_products(db: Session = Depends(get_db)):
    return db.query(Product).all()


@app.post("/api/products", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
def create_product(
    product_in: ProductCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    product = Product(**product_in.dict())
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@app.put("/api/products/{product_id}", response_model=ProductResponse)
def update_product(
    product_id: int,
    product_in: ProductCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    for key, value in product_in.dict().items():
        setattr(product, key, value)
    
    db.commit()
    db.refresh(product)
    return product


@app.delete("/api/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    db.delete(product)
    db.commit()
    return None


# ----------------- ORDER & CHECKOUT ROUTES -----------------
@app.post("/api/orders/checkout", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def checkout(
    payload: CheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not payload.items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    total_amount = 0.0
    order_items_to_create = []

    for item in payload.items:
        product = db.query(Product).filter(Product.id == item.product_id).with_for_update().first() if "sqlite" not in DATABASE_URL else db.query(Product).filter(Product.id == item.product_id).first()
        
        if not product:
            raise HTTPException(status_code=404, detail=f"Product #{item.product_id} not found")
        if product.stock < item.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient stock for '{product.name}'. Available: {product.stock}"
            )

        # Deduct stock and accumulate total
        product.stock -= item.quantity
        item_total = product.price * item.quantity
        total_amount += item_total

        order_items_to_create.append(
            OrderItem(
                product_id=product.id,
                product_name=product.name,
                quantity=item.quantity,
                unit_price=product.price
            )
        )

    order = Order(
        user_id=current_user.id,
        total_amount=round(total_amount, 2),
        status="PENDING",
        items=order_items_to_create
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


@app.get("/api/orders", response_model=List[OrderResponse])
def list_orders(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role == "admin":
        return db.query(Order).order_by(Order.id.desc()).all()
    return db.query(Order).filter(Order.user_id == current_user.id).order_by(Order.id.desc()).all()


@app.patch("/api/orders/{order_id}/status", response_model=OrderResponse)
def update_order_status(
    order_id: int,
    status_payload: StatusUpdateSchema,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    valid_statuses = ["PENDING", "PROCESSING", "SHIPPED", "DELIVERED", "CANCELLED"]
    if status_payload.status.upper() not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    order.status = status_payload.status.upper()
    db.commit()
    db.refresh(order)
    return order


# ----------------- EMBEDDED FRONTEND (HTML5 + Tailwind CSS + JS) -----------------
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Apex Commerce - Full-Stack Store</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen flex flex-col font-sans">

  <!-- Navigation Bar -->
  <nav class="sticky top-0 z-50 bg-slate-900/90 backdrop-blur border-b border-slate-800">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
      <div class="flex items-center justify-between h-16">
        <div class="flex items-center gap-3 cursor-pointer" onclick="navigate('catalog')">
          <div class="bg-indigo-600 p-2 rounded-xl text-white shadow-lg shadow-indigo-500/30">
            <i class="fa-solid fa-layer-group text-lg"></i>
          </div>
          <span class="text-xl font-bold tracking-tight text-white">Apex<span class="text-indigo-400">Store</span></span>
        </div>

        <div class="flex items-center gap-4">
          <button onclick="navigate('catalog')" class="text-slate-300 hover:text-white text-sm font-medium px-3 py-2 rounded-md transition">Catalog</button>
          <button id="nav-orders" onclick="navigate('orders')" class="hidden text-slate-300 hover:text-white text-sm font-medium px-3 py-2 rounded-md transition">Orders</button>
          <button id="nav-admin" onclick="navigate('admin')" class="hidden text-amber-400 hover:text-amber-300 text-sm font-medium px-3 py-2 rounded-md transition">Admin Portal</button>

          <!-- Cart Button -->
          <button onclick="navigate('cart')" class="relative p-2 text-slate-300 hover:text-white transition">
            <i class="fa-solid fa-cart-shopping text-lg"></i>
            <span id="cart-count" class="absolute -top-1 -right-1 bg-indigo-500 text-white text-xs font-bold w-5 h-5 flex items-center justify-center rounded-full">0</span>
          </button>

          <!-- User Section -->
          <div id="auth-actions" class="flex items-center gap-2 pl-2 border-l border-slate-800">
            <button onclick="navigate('auth')" class="bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold px-4 py-2 rounded-lg transition">Sign In</button>
          </div>
          <div id="user-profile" class="hidden flex items-center gap-3 pl-2 border-l border-slate-800">
            <span id="user-badge" class="text-xs bg-slate-800 text-slate-300 px-2.5 py-1 rounded-full border border-slate-700"></span>
            <button onclick="logout()" class="text-slate-400 hover:text-rose-400 text-sm transition" title="Sign Out"><i class="fa-solid fa-arrow-right-from-bracket"></i></button>
          </div>
        </div>
      </div>
    </div>
  </nav>

  <!-- Main Content Container -->
  <main class="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
    
    <!-- Notification Banner -->
    <div id="toast" class="fixed bottom-5 right-5 z-50 transform transition-all duration-300 translate-y-20 opacity-0 bg-slate-900 border border-slate-700 text-slate-100 px-4 py-3 rounded-xl shadow-2xl flex items-center gap-3">
      <i id="toast-icon" class="fa-solid fa-circle-check text-emerald-400"></i>
      <span id="toast-msg" class="text-sm font-medium">Notification</span>
    </div>

    <!-- VIEW: Catalog -->
    <section id="view-catalog" class="space-y-6">
      <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 class="text-2xl font-bold tracking-tight text-white">Explore Products</h1>
          <p class="text-slate-400 text-sm">Select top-tier hardware and accessories with verified stock.</p>
        </div>
      </div>
      <div id="product-grid" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6"></div>
    </section>

    <!-- VIEW: Shopping Cart -->
    <section id="view-cart" class="hidden space-y-6 max-w-3xl mx-auto">
      <h1 class="text-2xl font-bold text-white">Your Shopping Cart</h1>
      <div id="cart-items" class="space-y-3 bg-slate-900/60 p-6 rounded-2xl border border-slate-800 shadow-xl"></div>
      <div id="cart-summary" class="hidden bg-slate-900/80 p-6 rounded-2xl border border-slate-800 flex justify-between items-center">
        <div>
          <p class="text-xs text-slate-400 uppercase tracking-wider font-semibold">Total Amount</p>
          <p id="cart-total" class="text-2xl font-bold text-emerald-400">$0.00</p>
        </div>
        <button onclick="handleCheckout()" class="bg-indigo-600 hover:bg-indigo-500 text-white font-medium px-6 py-2.5 rounded-xl transition shadow-lg shadow-indigo-600/30 flex items-center gap-2">
          <span>Checkout Order</span>
          <i class="fa-solid fa-arrow-right text-xs"></i>
        </button>
      </div>
    </section>

    <!-- VIEW: Orders & Tracking -->
    <section id="view-orders" class="hidden space-y-6 max-w-4xl mx-auto">
      <div>
        <h1 class="text-2xl font-bold text-white">Order Tracking</h1>
        <p class="text-slate-400 text-sm">Monitor order fulfillment statuses and line item breakdowns.</p>
      </div>
      <div id="order-list" class="space-y-4"></div>
    </section>

    <!-- VIEW: Admin Panel -->
    <section id="view-admin" class="hidden space-y-8">
      <div>
        <h1 class="text-2xl font-bold text-white">Admin Management Portal</h1>
        <p class="text-slate-400 text-sm">Manage inventory catalog and update customer order fulfillment statuses.</p>
      </div>

      <!-- Add Product Form -->
      <div class="bg-slate-900/80 p-6 rounded-2xl border border-slate-800">
        <h2 class="text-lg font-semibold text-white mb-4">Add New Product</h2>
        <form onsubmit="handleCreateProduct(event)" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <input type="text" id="admin-pname" placeholder="Product Name" required class="bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500">
          <input type="number" step="0.01" id="admin-pprice" placeholder="Price ($)" required class="bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500">
          <input type="number" id="admin-pstock" placeholder="Stock Quantity" required class="bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500">
          <input type="text" id="admin-pimg" placeholder="Image URL (optional)" class="bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500">
          <textarea id="admin-pdesc" placeholder="Product Description..." class="sm:col-span-2 lg:col-span-3 bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"></textarea>
          <button type="submit" class="bg-emerald-600 hover:bg-emerald-500 text-white font-medium rounded-lg px-4 py-2 text-sm transition">Create Item</button>
        </form>
      </div>

      <!-- Inventory Table -->
      <div class="bg-slate-900/80 rounded-2xl border border-slate-800 overflow-hidden">
        <div class="px-6 py-4 border-b border-slate-800">
          <h2 class="font-semibold text-white">Active Product Inventory</h2>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-left text-sm text-slate-400">
            <thead class="bg-slate-950 text-xs uppercase tracking-wider text-slate-500 border-b border-slate-800">
              <tr>
                <th class="px-6 py-3">Product</th>
                <th class="px-6 py-3">Price</th>
                <th class="px-6 py-3">Stock</th>
                <th class="px-6 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody id="admin-inventory-body" class="divide-y divide-slate-800"></tbody>
          </table>
        </div>
      </div>
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
            <input type="text" id="auth-username" required class="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-indigo-500">
          </div>
          <div>
            <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Password</label>
            <input type="password" id="auth-password" required class="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-indigo-500">
          </div>
          <div id="auth-role-group" class="hidden">
            <label class="block text-xs font-semibold uppercase tracking-wider text-slate-400 mb-1">Account Role</label>
            <select id="auth-role" class="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-indigo-500">
              <option value="customer">Customer</option>
              <option value="admin">Administrator</option>
            </select>
          </div>
          <button type="submit" id="auth-submit-btn" class="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-medium py-2.5 rounded-lg transition shadow-lg shadow-indigo-600/30">Sign In</button>
        </form>

        <div class="mt-6 pt-4 border-t border-slate-800 text-xs text-slate-500 space-y-1">
          <p><strong>Demo Admin:</strong> admin / adminpassword</p>
          <p><strong>Demo Customer:</strong> customer / customerpassword</p>
        </div>
      </div>
    </section>

  </main>

  <script>
    // State Management
    let token = localStorage.getItem("token");
    let userRole = localStorage.getItem("role");
    let username = localStorage.getItem("username");
    let cart = JSON.parse(localStorage.getItem("cart") || "[]");
    let productsCache = [];
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

    function navigate(viewName) {
      ["catalog", "cart", "orders", "admin", "auth"].forEach(v => {
        document.getElementById(`view-${v}`).classList.add("hidden");
      });
      document.getElementById(`view-${viewName}`).classList.remove("hidden");

      if (viewName === "catalog") loadProducts();
      if (viewName === "cart") renderCart();
      if (viewName === "orders") loadOrders();
      if (viewName === "admin") {
        if (userRole !== "admin") return navigate("catalog");
        loadProducts();
      }
    }

    function updateNavState() {
      const authActions = document.getElementById("auth-actions");
      const userProfile = document.getElementById("user-profile");
      const navOrders = document.getElementById("nav-orders");
      const navAdmin = document.getElementById("nav-admin");
      const userBadge = document.getElementById("user-badge");

      if (token && username) {
        authActions.classList.add("hidden");
        userProfile.classList.remove("hidden");
        navOrders.classList.remove("hidden");
        userBadge.innerText = `${username} (${userRole})`;
        if (userRole === "admin") navAdmin.classList.remove("hidden");
        else navAdmin.classList.add("hidden");
      } else {
        authActions.classList.remove("hidden");
        userProfile.classList.add("hidden");
        navOrders.classList.add("hidden");
        navAdmin.classList.add("hidden");
      }
      updateCartBadge();
    }

    function setAuthMode(mode) {
      authMode = mode;
      const tabLogin = document.getElementById("tab-login");
      const tabRegister = document.getElementById("tab-register");
      const roleGroup = document.getElementById("auth-role-group");
      const btn = document.getElementById("auth-submit-btn");

      if (mode === "login") {
        tabLogin.className = "font-semibold text-indigo-400 border-b-2 border-indigo-400 pb-2 flex-1";
        tabRegister.className = "font-semibold text-slate-500 pb-2 flex-1";
        roleGroup.classList.add("hidden");
        btn.innerText = "Sign In";
      } else {
        tabRegister.className = "font-semibold text-indigo-400 border-b-2 border-indigo-400 pb-2 flex-1";
        tabLogin.className = "font-semibold text-slate-500 pb-2 flex-1";
        roleGroup.classList.remove("hidden");
        btn.innerText = "Create Account";
      }
    }

    async function handleAuth(e) {
      e.preventDefault();
      const u = document.getElementById("auth-username").value.trim();
      const p = document.getElementById("auth-password").value.trim();
      const r = document.getElementById("auth-role").value;

      try {
        if (authMode === "register") {
          const res = await fetch("/api/auth/register", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({username: u, password: p, role: r})
          });
          if (!res.ok) {
            const data = await res.json();
            throw new Error(data.detail || "Registration failed");
          }
          showToast("Account created! Logging in...");
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
        userRole = data.role;
        username = data.username;
        localStorage.setItem("token", token);
        localStorage.setItem("role", userRole);
        localStorage.setItem("username", username);

        updateNavState();
        showToast(`Welcome back, ${username}!`);
        navigate("catalog");
      } catch (err) {
        showToast(err.message, true);
      }
    }

    function logout() {
      token = null;
      userRole = null;
      username = null;
      localStorage.clear();
      updateNavState();
      showToast("Logged out successfully");
      navigate("catalog");
    }

    // Catalog & Products
    async function loadProducts() {
      try {
        const res = await fetch("/api/products");
        productsCache = await res.json();
        renderCatalog();
        if (userRole === "admin") renderAdminInventory();
      } catch (err) {
        showToast("Error loading catalog", true);
      }
    }

    function renderCatalog() {
      const grid = document.getElementById("product-grid");
      if (!productsCache.length) {
        grid.innerHTML = `<p class="text-slate-500 col-span-full">No products available in the catalog.</p>`;
        return;
      }
      grid.innerHTML = productsCache.map(p => `
        <div class="bg-slate-900/60 border border-slate-800 hover:border-slate-700 transition rounded-2xl overflow-hidden flex flex-col justify-between group">
          <div class="aspect-video w-full overflow-hidden bg-slate-950">
            <img src="${p.image_url}" alt="${p.name}" class="w-full h-full object-cover group-hover:scale-105 transition duration-300">
          </div>
          <div class="p-5 flex-1 flex flex-col justify-between">
            <div>
              <div class="flex justify-between items-start mb-2">
                <h3 class="font-semibold text-white group-hover:text-indigo-400 transition">${p.name}</h3>
                <span class="text-emerald-400 font-bold text-sm">$${p.price.toFixed(2)}</span>
              </div>
              <p class="text-xs text-slate-400 line-clamp-2 mb-4">${p.description}</p>
            </div>
            <div class="flex items-center justify-between pt-3 border-t border-slate-800/80">
              <span class="text-xs ${p.stock > 0 ? 'text-slate-400' : 'text-rose-400 font-semibold'}">
                ${p.stock > 0 ? `${p.stock} in stock` : 'Out of stock'}
              </span>
              <button 
                onclick="addToCart(${p.id})" 
                ${p.stock === 0 ? 'disabled' : ''}
                class="bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-600 text-white text-xs font-semibold px-3.5 py-2 rounded-xl transition flex items-center gap-1.5">
                <i class="fa-solid fa-cart-plus"></i> Add
              </button>
            </div>
          </div>
        </div>
      `).join("");
    }

    // Cart Management
    function addToCart(productId) {
      const prod = productsCache.find(p => p.id === productId);
      if (!prod || prod.stock <= 0) return showToast("Item out of stock", true);

      const existing = cart.find(item => item.product_id === productId);
      if (existing) {
        if (existing.quantity >= prod.stock) return showToast("Reached maximum available stock", true);
        existing.quantity++;
      } else {
        cart.push({ product_id: productId, quantity: 1 });
      }
      localStorage.setItem("cart", JSON.stringify(cart));
      updateCartBadge();
      showToast(`Added ${prod.name} to cart`);
    }

    function updateCartBadge() {
      const count = cart.reduce((sum, item) => sum + item.quantity, 0);
      document.getElementById("cart-count").innerText = count;
    }

    function updateCartQty(productId, change) {
      const item = cart.find(i => i.product_id === productId);
      const prod = productsCache.find(p => p.id === productId);
      if (!item) return;

      item.quantity += change;
      if (prod && item.quantity > prod.stock) {
        item.quantity = prod.stock;
        showToast("Maximum available stock reached", true);
      }
      if (item.quantity <= 0) cart = cart.filter(i => i.product_id !== productId);

      localStorage.setItem("cart", JSON.stringify(cart));
      updateCartBadge();
      renderCart();
    }

    function renderCart() {
      const container = document.getElementById("cart-items");
      const summary = document.getElementById("cart-summary");

      if (!cart.length) {
        container.innerHTML = `<div class="text-center py-10 text-slate-500"><i class="fa-solid fa-basket-shopping text-3xl mb-2"></i><p>Your cart is empty.</p></div>`;
        summary.classList.add("hidden");
        return;
      }

      let total = 0;
      container.innerHTML = cart.map(item => {
        const product = productsCache.find(p => p.id === item.product_id);
        if (!product) return "";
        const itemTotal = product.price * item.quantity;
        total += itemTotal;

        return `
          <div class="flex items-center justify-between p-3.5 bg-slate-950/40 rounded-xl border border-slate-800">
            <div class="flex items-center gap-4">
              <img src="${product.image_url}" class="w-12 h-12 object-cover rounded-lg">
              <div>
                <p class="font-medium text-sm text-white">${product.name}</p>
                <p class="text-xs text-slate-400">$${product.price.toFixed(2)} each</p>
              </div>
            </div>
            <div class="flex items-center gap-4">
              <div class="flex items-center bg-slate-900 border border-slate-800 rounded-lg">
                <button onclick="updateCartQty(${product.id}, -1)" class="px-2.5 py-1 text-slate-400 hover:text-white">-</button>
                <span class="px-2 text-xs font-semibold">${item.quantity}</span>
                <button onclick="updateCartQty(${product.id}, 1)" class="px-2.5 py-1 text-slate-400 hover:text-white">+</button>
              </div>
              <p class="text-sm font-semibold text-emerald-400 w-20 text-right">$${itemTotal.toFixed(2)}</p>
              <button onclick="updateCartQty(${product.id}, -${item.quantity})" class="text-slate-500 hover:text-rose-400 p-1"><i class="fa-solid fa-trash-can"></i></button>
            </div>
          </div>
        `;
      }).join("");

      document.getElementById("cart-total").innerText = `$${total.toFixed(2)}`;
      summary.classList.remove("hidden");
    }

    async function handleCheckout() {
      if (!token) {
        showToast("Please sign in to complete checkout", true);
        return navigate("auth");
      }

      try {
        const res = await fetch("/api/orders/checkout", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${token}`
          },
          body: JSON.stringify({ items: cart })
        });

        if (!res.ok) {
          const data = await res.json();
          throw new Error(data.detail || "Checkout failed");
        }

        cart = [];
        localStorage.removeItem("cart");
        updateCartBadge();
        showToast("Order placed successfully!");
        navigate("orders");
      } catch (err) {
        showToast(err.message, true);
      }
    }

    // Orders & Tracking
    async function loadOrders() {
      if (!token) return navigate("auth");
      try {
        const res = await fetch("/api/orders", {
          headers: { "Authorization": `Bearer ${token}` }
        });
        if (!res.ok) throw new Error("Failed to load orders");
        const orders = await res.json();
        renderOrders(orders);
      } catch (err) {
        showToast(err.message, true);
      }
    }

    function renderOrders(orders) {
      const container = document.getElementById("order-list");
      if (!orders.length) {
        container.innerHTML = `<p class="text-slate-500">No orders found.</p>`;
        return;
      }

      const statusColors = {
        "PENDING": "bg-amber-500/10 text-amber-400 border-amber-500/20",
        "PROCESSING": "bg-indigo-500/10 text-indigo-400 border-indigo-500/20",
        "SHIPPED": "bg-cyan-500/10 text-cyan-400 border-cyan-500/20",
        "DELIVERED": "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
        "CANCELLED": "bg-rose-500/10 text-rose-400 border-rose-500/20",
      };

      container.innerHTML = orders.map(o => `
        <div class="bg-slate-900/70 border border-slate-800 rounded-2xl p-5 space-y-4">
          <div class="flex flex-col sm:flex-row sm:items-center justify-between border-b border-slate-800 pb-3 gap-2">
            <div>
              <p class="font-bold text-white">Order #${o.id}</p>
              <p class="text-xs text-slate-400">${new Date(o.created_at).toLocaleString()}</p>
            </div>
            <div class="flex items-center gap-3">
              <span class="text-xs font-semibold px-3 py-1 rounded-full border ${statusColors[o.status] || ''}">${o.status}</span>
              ${userRole === "admin" ? `
                <select onchange="updateOrderStatus(${o.id}, this.value)" class="bg-slate-950 border border-slate-700 text-xs rounded-lg px-2 py-1 text-white">
                  <option value="" disabled selected>Update Status</option>
                  <option value="PROCESSING">PROCESSING</option>
                  <option value="SHIPPED">SHIPPED</option>
                  <option value="DELIVERED">DELIVERED</option>
                  <option value="CANCELLED">CANCELLED</option>
                </select>
              ` : ''}
            </div>
          </div>
          <div class="divide-y divide-slate-800/60">
            ${o.items.map(i => `
              <div class="py-2 flex justify-between text-xs">
                <span class="text-slate-300">${i.product_name} <span class="text-slate-500">x${i.quantity}</span></span>
                <span class="font-semibold text-slate-300">$${(i.unit_price * i.quantity).toFixed(2)}</span>
              </div>
            `).join("")}
          </div>
          <div class="flex justify-between items-center pt-2 border-t border-slate-800 font-medium text-sm">
            <span class="text-slate-400">Total Charged</span>
            <span class="text-emerald-400 font-bold">$${o.total_amount.toFixed(2)}</span>
          </div>
        </div>
      `).join("");
    }

    async function updateOrderStatus(orderId, newStatus) {
      try {
        const res = await fetch(`/api/orders/${orderId}/status`, {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${token}`
          },
          body: JSON.stringify({ status: newStatus })
        });
        if (!res.ok) throw new Error("Failed to update status");
        showToast(`Order #${orderId} status updated to ${newStatus}`);
        loadOrders();
      } catch (err) {
        showToast(err.message, true);
      }
    }

    // Admin Inventory Management
    function renderAdminInventory() {
      const tbody = document.getElementById("admin-inventory-body");
      tbody.innerHTML = productsCache.map(p => `
        <tr class="hover:bg-slate-950/50 transition">
          <td class="px-6 py-4 flex items-center gap-3">
            <img src="${p.image_url}" class="w-8 h-8 rounded object-cover">
            <span class="font-medium text-white">${p.name}</span>
          </td>
          <td class="px-6 py-4">$${p.price.toFixed(2)}</td>
          <td class="px-6 py-4">${p.stock}</td>
          <td class="px-6 py-4 text-right">
            <button onclick="deleteProduct(${p.id})" class="text-rose-400 hover:text-rose-300 text-xs font-semibold px-2 py-1 bg-rose-500/10 rounded border border-rose-500/20">Delete</button>
          </td>
        </tr>
      `).join("");
    }

    async function handleCreateProduct(e) {
      e.preventDefault();
      const payload = {
        name: document.getElementById("admin-pname").value,
        price: parseFloat(document.getElementById("admin-pprice").value),
        stock: parseInt(document.getElementById("admin-pstock").value),
        description: document.getElementById("admin-pdesc").value,
        image_url: document.getElementById("admin-pimg").value || undefined
      };

      try {
        const res = await fetch("/api/products", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${token}`
          },
          body: JSON.stringify(payload)
        });
        if (!res.ok) throw new Error("Failed to create product");
        showToast("Product created successfully");
        e.target.reset();
        loadProducts();
      } catch (err) {
        showToast(err.message, true);
      }
    }

    async function deleteProduct(id) {
      if (!confirm("Are you sure you want to delete this product?")) return;
      try {
        const res = await fetch(`/api/products/${id}`, {
          method: "DELETE",
          headers: { "Authorization": `Bearer ${token}` }
        });
        if (!res.ok) throw new Error("Failed to delete product");
        showToast("Product deleted");
        loadProducts();
      } catch (err) {
        showToast(err.message, true);
      }
    }

    // Initialization
    updateNavState();
    loadProducts();
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