# Swift Prosys Production Dashboard


bash
cd swiftprosys
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

python manage.py makemigrations accounts branches mapping projects inventory dashboard
python manage.py migrate
python manage.py seed_data        # creates branches, admin login, syncs mapping templates

python manage.py runserver


Open http://127.0.0.1:8000 and log in with:
- **username:** `admin`
- **password:** `admin12345` (change this immediately — `python manage.py changepassword admin`)

