import os
import tempfile
import zipfile
import shutil
import random
import requests
from flask import Flask, request, jsonify, render_template, session
from flask_cors import CORS
import geopandas as gpd

# -----------------------------------------
# CONFIGURATION
# -----------------------------------------
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.secret_key = "YOUR_SECRET_KEY"  # change this
CORS(app)

ADMIN_USER = "admin"
ADMIN_PASS = "1234"

layers = {}  # Stores all layers: name → {geojson, color, opacity, zip_path}

# -----------------------------------------
# GITHUB SHAPEFILES (raw URLs)
# -----------------------------------------
GITHUB_SHAPEFILES = {
    "P_Location": "https://github.com/himgis/webgis/raw/master/uploads/P_Location.zip",
    "Kheda_Web_Map1": "https://github.com/himgis/webgis/raw/master/uploads/Kheda_Web_Map1.zip"
}
# -----------------------------------------
# LOGIN PAGE
# -----------------------------------------
@app.route("/login", methods=["GET"])
def login_page():
    return render_template("login.html")

@app.route("/login", methods=["POST"])
def login_api():
    data = request.get_json()
    if data["username"] == ADMIN_USER and data["password"] == ADMIN_PASS:
        session["admin"] = True
        return jsonify({"message": "Logged in"})
    else:
        return jsonify({"error": "Invalid username or password"}), 401

@app.route("/logout")
def logout():
    session.pop("admin", None)
    return jsonify({"message": "Logged out"})

# -----------------------------------------
# HOME PAGE (MAP)
# -----------------------------------------
@app.route("/")
def index():
    is_admin = session.get("admin", False)
    return render_template("map.html", is_admin=is_admin)

# -----------------------------------------
# UPLOAD PAGE (ADMIN ONLY)
# -----------------------------------------
@app.route("/upload_page")
def upload_page():
    if not session.get("admin"):
        return "Unauthorized", 403
    return render_template("upload_page.html")

# -----------------------------------------
# UPLOAD SHAPEFILES
# -----------------------------------------
@app.route("/upload", methods=["POST"])
def upload_shapefiles():
    if not session.get("admin"):
        return jsonify({"error": "Only admin can upload!"}), 403

    if "files" not in request.files:
        return jsonify({"error": "No files received!"}), 400

    files = request.files.getlist("files")
    uploaded = []
    failed = []

    for file in files:
        if not file.filename.lower().endswith(".zip"):
            failed.append(file.filename)
            continue

        zip_path = os.path.join(UPLOAD_FOLDER, file.filename)
        file.save(zip_path)

        if load_zip_into_layers(zip_path):
            uploaded.append(os.path.splitext(file.filename)[0])
        else:
            failed.append(file.filename)

    return jsonify({"uploaded": uploaded, "failed": failed})

# -----------------------------------------
# DELETE LAYER
# -----------------------------------------
@app.route("/delete/<layer_name>", methods=["DELETE"])
def delete_layer(layer_name):
    if not session.get("admin"):
        return jsonify({"error": "Only admin can delete!"}), 403

    if layer_name in layers:
        zip_path = layers[layer_name].get("zip_path")
        if zip_path and os.path.exists(zip_path):
            os.remove(zip_path)
        layers.pop(layer_name)
        return jsonify({"message": "Deleted"})
    else:
        return jsonify({"error": "Layer not found"}), 404

# -----------------------------------------
# SEND LAYER INFO TO FRONTEND
# -----------------------------------------
@app.route("/layers")
def get_layers():
    is_admin = session.get("admin", False)

    final_bounds = None
    if layers:
        all_bounds = []
        for lyr in layers.values():
            gdf = gpd.GeoDataFrame.from_features(lyr["geojson"]["features"], crs="EPSG:4326")
            all_bounds.append(gdf.total_bounds)

        minx = min(b[0] for b in all_bounds)
        miny = min(b[1] for b in all_bounds)
        maxx = max(b[2] for b in all_bounds)
        maxy = max(b[3] for b in all_bounds)

        final_bounds = [[miny, minx], [maxy, maxx]]

    return jsonify({
        "is_admin": is_admin,
        "layers": layers,
        "bounds": final_bounds
    })

# -----------------------------------------
# HELPER FUNCTION: LOAD ZIP INTO LAYERS
# -----------------------------------------
def load_zip_into_layers(zip_path):
    temp_dir = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(temp_dir)

        shp_file = None
        for root, dirs, files2 in os.walk(temp_dir):
            for f in files2:
                if f.lower().endswith(".shp"):
                    shp_file = os.path.join(root, f)
                    break

        if not shp_file:
            return False

        gdf = gpd.read_file(shp_file)
        geojson_dict = gdf.to_crs("EPSG:4326").__geo_interface__
        layer_name = os.path.splitext(os.path.basename(zip_path))[0]
        color = "#{:06x}".format(random.randint(0, 0xFFFFFF))

        layers[layer_name] = {
            "geojson": geojson_dict,
            "color": color,
            "opacity": 0.7,
            "zip_path": zip_path
        }
        return True

    except Exception as e:
        print("ERROR loading:", zip_path, e)
        return False

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

# -----------------------------------------
# LOAD SHAPEFILES FROM GITHUB ON STARTUP
# -----------------------------------------
def load_github_shapefiles():
    for layer_name, url in GITHUB_SHAPEFILES.items():
        zip_path = os.path.join(UPLOAD_FOLDER, f"{layer_name}.zip")
        if not os.path.exists(zip_path):
            try:
                r = requests.get(url)
                r.raise_for_status()
                with open(zip_path, "wb") as f:
                    f.write(r.content)
                print(f"Downloaded {layer_name} from GitHub")
            except Exception as e:
                print(f"Failed to download {layer_name}: {e}")
                continue
        load_zip_into_layers(zip_path)

load_github_shapefiles()

# -----------------------------------------
# RUN SERVER
# -----------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
