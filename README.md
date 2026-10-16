# School Bus Tracking System

A Flask + SQLite academic prototype for school transport administration. The project includes role-specific workspaces, bus and driver management, student records, GPS location updates, attendance history, profile editing, and parent notifications.

## Requirements
- Python 3.10 or newer
- Flask 3.x (`pip install -r requirements.txt`)
- A modern browser

## Run on Windows
1. Extract the ZIP archive into a normal folder (do not run it from inside the ZIP preview).
2. Open the extracted `SchoolBusTrackingSystem_NEW` folder.
3. Double-click `run.bat`, or open Command Prompt in this folder and run:
   ```bat
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   python app.py
   ```
4. Open `http://127.0.0.1:5000` in your browser.

The SQLite database is created automatically on first run. Back up `database.db` before replacing project files if you have entered real test records.

## Demo accounts
These accounts are created if they do not already exist:
- Admin: `admin@school.com` / `admin123`
- Driver: `driver@school.com` / `driver123`
- Parent: `parent@school.com` / `parent123`

Change demo passwords before using any real personal data. Public registration supports Parent, Driver, and Teacher roles. The Admin role is not offered in public registration.

## Main features
- **Role access:** Admin, Driver, Parent, and Teacher use separate workspaces and server-side role checks.
- **Admin bus management:** create buses; edit registration, route, and assigned driver; leave a bus unassigned and assign a driver later; upload/replace each bus photo.
- **Driver management:** create driver accounts, upload genuine driver photos, and activate/deactivate driver accounts. A driver cannot be assigned to more than one bus at a time.
- **Teacher management:** administrator can create teacher accounts and activate/deactivate them.
- **Parent and student linking:** administrator links each student record to a parent account. Parents see only linked children, their attendance, relevant route buses, assigned driver profiles, and their notifications.
- **Attendance:** Admin, Driver, and Teacher can record Boarded, Absent, or Dropped off status. Drivers are limited to their assigned route and bus. Parents can filter their linked children's attendance by month.
- **Arrival notifications:** when a driver changes the bus status to `Arrived at School`, parents linked to students on that bus route receive an in-app notification. This is an in-app notification, not an SMS or push notification.
- **GPS:** the driver page can send browser GPS coordinates after location permission is granted and the site is served in a browser context that permits geolocation.
- **Profiles:** users can update their own name, email, profile photo, and password.

## Important setup and testing notes
- Assign student routes and bus routes consistently so attendance filtering and arrival notifications match the right children.
- A parent must be linked to a student by the administrator before that student's information is visible in the parent workspace.
- Use real, school-approved bus and driver photos. The supplied school-bus image is a visual fallback, not proof of a particular bus identity.
- The prototype uses SQLite and a development secret fallback. Before deployment, set `SCHOOL_BUS_SECRET_KEY` to a strong secret, use HTTPS, back up the database, and review privacy/retention requirements for children's information and GPS data.
- Live browser testing should be completed on the target laptop before an academic demonstration. Flask must be installed from `requirements.txt` first.
