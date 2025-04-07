import folium
import os
import json
from flask import Flask, render_template_string, request, jsonify
from folium.plugins import Draw
from datetime import datetime

# Directory to save GeoJSON files
GEOJSON_DIR = "./geojsons"
os.makedirs(GEOJSON_DIR, exist_ok=True)

# Flask app setup
app = Flask(__name__)

@app.route("/")
def map_view():
    """Display the map for drawing polygons and rectangles."""
    m = folium.Map(location=[37.7749, -122.4194], zoom_start=12)

    # Add drawing controls
    draw = Draw(
        export=True,  # Enable export button for debugging
        draw_options={
            "polyline": False,
            "circle": False,
            "marker": False,
            "circlemarker": False,
            "polygon": True,
            "rectangle": True,
        },
        edit_options={"edit": True}
    )
    draw.add_to(m)

    map_html = m._repr_html_()

    return render_template_string("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>AOI GeoJSON Generator</title>
            <style>
                #map { width: 100%; height: 80vh; margin-bottom: 10px; }
                .control-panel { margin: 10px 0; padding: 10px; background: #f5f5f5; }
                .error { color: red; }
                .success { color: green; }
                .search-box { margin-bottom: 10px; }
            </style>
            <script src="https://cdn.jsdelivr.net/npm/axios/dist/axios.min.js"></script>
            <script>
                let drawnItems;
                let map;

                window.addEventListener('load', function() {
                    // Map is already created by folium, just need to get reference
                    map = document.querySelector('#map').querySelector('.folium-map')._leaflet_map;

                    // Get reference to the draw control's feature group
                    map.eachLayer(function(layer) {
                        if (layer instanceof L.FeatureGroup) {
                            drawnItems = layer;
                        }
                    });

                    // Add event handlers
                    map.on('draw:created', function (e) {
                        const layer = e.layer;

                        if (drawnItems) {
                            drawnItems.clearLayers(); // Clear previous drawings
                            drawnItems.addLayer(layer); // Add the new layer
                        }

                        document.getElementById('status').innerHTML =
                            '<span class="success">Area drawn successfully. Ready to save.</span>';
                    });

                    map.on('draw:deleted', function() {
                        document.getElementById('status').innerText = 'Draw a new AOI.';
                    });
                });

                async function searchLocation() {
                    const query = document.getElementById('searchQuery').value;
                    if (!query) return;

                    try {
                        const response = await axios.get(
                            `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}`
                        );
                        if (response.data && response.data.length > 0) {
                            const location = response.data[0];
                            map.setView([location.lat, location.lon], 12);
                            document.getElementById('searchStatus').textContent = `Found: ${location.display_name}`;
                        } else {
                            document.getElementById('searchStatus').textContent = 'Location not found';
                        }
                    } catch (error) {
                        document.getElementById('searchStatus').textContent = 'Search failed';
                        console.error(error);
                    }
                }

                async function saveAOI() {
                    const aoiName = document.getElementById("aoiName").value.trim();
                    if (!aoiName) {
                        document.getElementById("status").innerHTML =
                            '<span class="error">Error: AOI name is required.</span>';
                        return;
                    }

                    if (!drawnItems || drawnItems.getLayers().length === 0) {
                        document.getElementById("status").innerHTML =
                            '<span class="error">Error: Draw an area first.</span>';
                        return;
                    }

                    try {
                        const geojsonData = drawnItems.toGeoJSON();

                        // Add metadata
                        geojsonData.features[0].properties = {
                            aoi_name: aoiName,
                            created_at: new Date().toISOString(),
                        };

                        const response = await axios.post('/save', {
                            aoi_name: aoiName,
                            geojson: geojsonData,
                        });

                        document.getElementById("status").innerHTML =
                            `<span class="success">${response.data.message}</span>`;
                        document.getElementById("aoiName").value = '';
                        drawnItems.clearLayers();
                    } catch (error) {
                        console.error("Error in saveAOI:", error);
                        document.getElementById("status").innerHTML =
                            `<span class="error">Error saving AOI: ${error.message}</span>`;
                    }
                }

                function clearMap() {
                    if (drawnItems) {
                        drawnItems.clearLayers();
                        document.getElementById('status').innerText = 'Map cleared. Draw a new AOI.';
                    }
                }
            </script>
        </head>
        <body>
            <h2>Draw and Save AOI</h2>
            <div class="control-panel">
                <div class="search-box">
                    <input type="text" id="searchQuery" placeholder="Search location..." style="width: 50%;" />
                    <button onclick="searchLocation()">Search</button>
                    <div id="searchStatus"></div>
                </div>
                <input type="text" id="aoiName" placeholder="Enter AOI Name (required)" style="width: 50%;" />
                <button onclick="saveAOI()">Save AOI</button>
                <button onclick="clearMap()">Clear Map</button>
            </div>
            <div id="map">
                {{ map_html|safe }}
            </div>
            <p id="status"></p>
        </body>
        </html>
    """, map_html=map_html)

@app.route("/save", methods=["POST"])
def save_aoi():
    """Save the GeoJSON with metadata to the specified directory."""
    try:
        data = request.get_json()
        aoi_name = data.get("aoi_name")
        geojson = data.get("geojson")

        if not aoi_name or not geojson:
            return jsonify({"message": "Error: Missing AOI name or GeoJSON data."}), 400

        # Validate GeoJSON structure
        if not geojson.get("features") or not geojson["features"][0].get("geometry"):
            return jsonify({"message": "Error: Invalid GeoJSON structure."}), 400

        # Create a filename based on AOI name and timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{aoi_name}_{timestamp}.geojson"
        filepath = os.path.join(GEOJSON_DIR, filename)

        # Save the GeoJSON to file
        with open(filepath, "w") as f:
            json.dump(geojson, f, indent=2)

        return jsonify({"message": f"AOI saved successfully as {filename}."})
    except Exception as e:
        return jsonify({"message": f"Error saving AOI: {str(e)}"}), 500

def start_aoi_server():
    """Start the Flask app for generating AOIs."""
    app.run(debug=True, use_reloader=False)

if __name__ == "__main__":
    start_aoi_server()
