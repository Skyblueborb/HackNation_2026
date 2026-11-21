"""Backend API for Odwołania2json.

Owns the SQLite database (on the server side only) and exposes the HTTP API
consumed by the React frontend. No document data is ever bundled with this
package -- paths and credentials come from environment variables at runtime.
"""
