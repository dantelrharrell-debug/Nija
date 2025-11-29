from flask import Flask

# Create Flask instance
app = Flask(__name__)

# Example route
@app.route("/")
def home():
    return "Hello World! NIJA Trading Bot is live."

# Additional routes can go here
