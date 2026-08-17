import os
from flask import Flask, request, jsonify, render_template_string
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

# --- DATABASE CONFIGURATION ---
# Uses PostgreSQL on production (e.g., Render/Railway/Heroku) or fallback SQLite locally
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///portfolio.db")
# Fix legacy postgres:// URI format if provided by older deployment platforms
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# --- DATABASE MODEL ---
class Project(db.Model):
    __tablename__ = "projects"
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=False)
    tags = db.Column(db.String(255), default="")
    live_url = db.Column(db.String(255), default="#")
    github_url = db.Column(db.String(255), default="#")

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "tags": [t.strip() for t in self.tags.split(",") if t.strip()],
            "live_url": self.live_url,
            "github_url": self.github_url
        }

# Initialize Database and Seed Default Data
with app.app_context():
    db.create_all()
    if Project.query.count() == 0:
        seed_projects = [
            Project(
                title="Full-Stack Web Engine",
                description="A unified web application demonstrating REST APIs, database persistence, and dynamic client-side rendering.",
                tags="Python, Flask, SQLAlchemy, JavaScript",
                live_url="#",
                github_url="https://github.com"
            ),
            Project(
                title="Financial Analytics & Ledger Dashboard",
                description="A reporting module for calculating and visualizing ledgers, balance sheets, and key performance ratios.",
                tags="Python, SQLite, REST API, ChartJS",
                live_url="#",
                github_url="https://github.com"
            )
        ]
        db.session.bulk_save_objects(seed_projects)
        db.session.commit()

# --- BACKEND API ROUTES ---

@app.route("/api/projects", methods=["GET"])
def get_projects():
    projects = Project.query.order_by(Project.id.desc()).all()
    return jsonify({"success": True, "data": [p.to_dict() for p in projects]})

@app.route("/api/projects", methods=["POST"])
def add_project():
    data = request.get_json() or {}
    title = data.get("title")
    description = data.get("description")

    if not title or not description:
        return jsonify({"success": False, "message": "Title and description are required"}), 400

    new_project = Project(
        title=title,
        description=description,
        tags=data.get("tags", ""),
        live_url=data.get("live_url", "#"),
        github_url=data.get("github_url", "#")
    )
    db.session.add(new_project)
    db.session.commit()
    return jsonify({"success": True, "data": new_project.to_dict()}), 201

# --- FRONTEND ROUTE (Embedded Modern UI) ---

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Developer Portfolio & Showcase</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #0f172a;
      --card-bg: #1e293b;
      --border: #334155;
      --primary: #38bdf8;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --tag-bg: #0369a1;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Inter', sans-serif; }
    body { background-color: var(--bg); color: var(--text); line-height: 1.6; padding: 0 1rem; }
    .container { max-width: 1000px; margin: 0 auto; padding: 3rem 0; }
    
    header { text-align: center; margin-bottom: 3.5rem; }
    header h1 { font-size: 2.5rem; font-weight: 700; color: #fff; margin-bottom: 0.5rem; }
    header p { color: var(--text-muted); font-size: 1.1rem; }
    
    .skills-section { display: flex; justify-content: center; gap: 0.75rem; flex-wrap: wrap; margin-top: 1.5rem; }
    .skill-pill { background: var(--border); padding: 0.4rem 0.9rem; border-radius: 9999px; font-size: 0.85rem; font-weight: 500; }
    
    .section-title { font-size: 1.5rem; font-weight: 600; margin-bottom: 1.5rem; border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; }
    
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 1.5rem; margin-bottom: 3rem; }
    .card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; display: flex; flex-direction: column; justify-content: space-between; }
    .card h3 { font-size: 1.25rem; margin-bottom: 0.75rem; color: #fff; }
    .card p { color: var(--text-muted); font-size: 0.95rem; margin-bottom: 1rem; flex-grow: 1; }
    
    .tags { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 1.25rem; }
    .tag { background: var(--tag-bg); color: #fff; font-size: 0.75rem; padding: 0.2rem 0.6rem; border-radius: 6px; }
    
    .links { display: flex; gap: 1rem; }
    .links a { color: var(--primary); text-decoration: none; font-size: 0.9rem; font-weight: 500; }
    .links a:hover { text-decoration: underline; }
    
    .form-container { background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px; padding: 2rem; }
    .form-group { margin-bottom: 1rem; }
    label { display: block; font-size: 0.85rem; margin-bottom: 0.4rem; color: var(--text-muted); }
    input, textarea { width: 100%; padding: 0.75rem; background: #0b1120; border: 1px solid var(--border); border-radius: 6px; color: #fff; font-size: 0.95rem; }
    input:focus, textarea:focus { outline: 1px solid var(--primary); }
    button { background: var(--primary); color: #0f172a; font-weight: 600; border: none; padding: 0.75rem 1.5rem; border-radius: 6px; cursor: pointer; transition: opacity 0.2s; }
    button:hover { opacity: 0.9; }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>Full-Stack Portfolio</h1>
      <p>Showcasing production-ready web apps, scalable backend APIs, and projects.</p>
      <div class="skills-section">
        <span class="skill-pill">Python</span>
        <span class="skill-pill">Flask</span>
        <span class="skill-pill">SQL / PostgreSQL</span>
        <span class="skill-pill">JavaScript</span>
        <span class="skill-pill">RESTful APIs</span>
      </div>
    </header>

    <h2 class="section-title">Projects</h2>
    <div id="projects-grid" class="grid">
      <!-- Dynamic Project Cards Render Here -->
    </div>

    <div class="form-container">
      <h2 class="section-title" style="border: none; margin-bottom: 1rem;">Add New Project</h2>
      <form id="add-project-form">
        <div class="form-group">
          <label for="title">Project Title *</label>
          <input type="text" id="title" required placeholder="e.g. Real-Time Tracking App">
        </div>
        <div class="form-group">
          <label for="description">Description *</label>
          <textarea id="description" rows="3" required placeholder="Describe key features, database structure, and architecture..."></textarea>
        </div>
        <div class="form-group">
          <label for="tags">Tech Stack (comma-separated)</label>
          <input type="text" id="tags" placeholder="Python, Flask, PostgreSQL">
        </div>
        <div class="form-group">
          <label for="github_url">GitHub Repository URL</label>
          <input type="url" id="github_url" placeholder="https://github.com/username/repo">
        </div>
        <div class="form-group">
          <label for="live_url">Live Demo URL</label>
          <input type="url" id="live_url" placeholder="https://demo-app.onrender.com">
        </div>
        <button type="submit">Save Project to Database</button>
      </form>
    </div>
  </div>

  <script>
    async function loadProjects() {
      const grid = document.getElementById('projects-grid');
      try {
        const res = await fetch('/api/projects');
        const json = await res.json();
        if (!json.success || json.data.length === 0) {
          grid.innerHTML = '<p style="color: var(--text-muted);">No projects added yet.</p>';
          return;
        }
        grid.innerHTML = json.data.map(p => `
          <div class="card">
            <div>
              <h3>${p.title}</h3>
              <p>${p.description}</p>
            </div>
            <div>
              <div class="tags">
                ${(p.tags || []).map(t => `<span class="tag">${t}</span>`).join('')}
              </div>
              <div class="links">
                ${p.github_url && p.github_url !== '#' ? `<a href="${p.github_url}" target="_blank">GitHub &rarr;</a>` : ''}
                ${p.live_url && p.live_url !== '#' ? `<a href="${p.live_url}" target="_blank">Live Demo &rarr;</a>` : ''}
              </div>
            </div>
          </div>
        `).join('');
      } catch (err) {
        grid.innerHTML = '<p style="color: #ef4444;">Failed to load projects from server.</p>';
      }
    }

    document.getElementById('add-project-form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const payload = {
        title: document.getElementById('title').value,
        description: document.getElementById('description').value,
        tags: document.getElementById('tags').value,
        github_url: document.getElementById('github_url').value,
        live_url: document.getElementById('live_url').value
      };

      const res = await fetch('/api/projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (res.ok) {
        document.getElementById('add-project-form').reset();
        loadProjects();
      } else {
        alert('Failed to save project. Ensure all required fields are filled.');
      }
    });

    loadProjects();
  </script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)