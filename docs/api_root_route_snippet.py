"""
Add this route to src/api.py, anywhere alongside the other routes (e.g.
right after the `health()` route). It gives http://127.0.0.1:5050/ a
helpful response instead of Flask's default "Not Found" page, for anyone
who opens the API's URL directly in a browser instead of the dashboard's.

This is a convenience/clarity fix only -- the API was never broken. Flask
simply has no route for "/" by default, and 127.0.0.1:5050 is the backend
API, not the dashboard. The actual dashboard runs on a different port via
`npm run dev` (http://localhost:5173 by default).
"""

# --- paste into src/api.py, near the health() route ---

@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "service": "Churn Early-Warning API",
        "status": "running",
        "note": (
            "This is the backend API, not the dashboard. "
            "Open the dashboard at http://localhost:5173 instead "
            "(run `npm run dev` in the frontend/ folder)."
        ),
        "try_instead": [
            "/health",
            "/api/dashboard/summary",
            "/api/dashboard/accounts",
        ],
    })
