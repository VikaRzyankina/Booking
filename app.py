from flask import Flask

from routes.building_routes import building_bp
from routes.user_routes import user_bp

app = Flask(__name__)
app.secret_key = 'ОднаждыТутБудетКлюч'

app.register_blueprint(user_bp)
app.register_blueprint(building_bp)

if __name__ == '__main__':
    app.run(debug=True)
