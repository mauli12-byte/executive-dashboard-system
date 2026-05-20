from flask import Flask, render_template

app = Flask(__name__)

@app.route("/")
def dashboard():

    stats = {
        "companies": 2450,
        "executives": 12450,
        "sectors": 18,
        "contacted": 5400
    }

    return render_template("dashboard.html", stats=stats)

if __name__ == "__main__":
    app.run(debug=True)