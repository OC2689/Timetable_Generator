# University Timetable Generator

An AI-powered university timetable scheduling system built using **Python, Flask, SQLite, and Constraint Satisfaction Problem (CSP) techniques**.

The project automatically generates university timetables while considering scheduling constraints such as faculty availability, classroom allocation, subject requirements, and time-slot conflicts.

## 🚀 Project Overview

Creating a university timetable manually can be time-consuming and often leads to scheduling conflicts.

This project aims to automate the timetable generation process using Artificial Intelligence and Constraint Satisfaction techniques.

The system uses a CSP-based solver to assign subjects, faculty members, classrooms, and time slots while satisfying scheduling constraints.

## ✨ Features

- **Automated Timetable Generation:** Generates timetables using a CSP-based scheduling algorithm.
- **Constraint Handling:** Considers scheduling constraints to avoid conflicting assignments.
- **Backtracking Search:** Uses backtracking to explore possible timetable arrangements.
- **MRV Heuristic:** Uses the Minimum Remaining Values heuristic for variable selection.
- **Forward Checking:** Helps identify constraint violations early.
- **Constraint Propagation:** Reduces possible assignments during the search process.
- **Local Search:** Supports timetable optimization.
- **Flask Web Interface:** Provides a browser-based interface for interacting with the system.
- **SQLite Database:** Stores application data.
- **Performance Metrics:** Compares scheduling strategies using solver metrics.

## 🛠️ Technologies Used

| Technology | Purpose |
|---|---|
| Python | Core programming language |
| Flask | Web application framework |
| SQLite | Database management |
| CSP | Timetable scheduling approach |
| Backtracking | Search algorithm |
| MRV | Heuristic for variable selection |
| Forward Checking | Constraint checking |
| HTML/CSS | Web interface |

## 📂 Project Structure

```text
AI-Timetable-Generator/
│
├── app.py
├── csp_solver.py
├── README.md
├── requirements.txt
├── .gitignore
│
├── templates/
│   ├── login.html
│   ├── dashboard.html
│   ├── timetable.html
│   └── change_password.html
│
├── static/
│   └── (CSS, JavaScript, images)
│
└── timetable.db
```

*Note: The database is generated automatically by the application when needed. The `static/` directory is optional if your project does not use static files. The templates directory should contain the HTML files referenced by the Flask application.*

## ⚙️ Installation and Setup

### 1. Clone the Repository

```bash
git clone https://github.com/YOUR-USERNAME/AI-Timetable-Generator.git
```

### 2. Navigate to the Project Directory

```bash
cd AI-Timetable-Generator
```

### 3. Create a Virtual Environment

```bash
python3 -m venv venv
```

### 4. Activate the Virtual Environment

**Mac/Linux:**

```bash
source venv/bin/activate
```

**Windows:**

```bash
venv\Scripts\activate
```

### 5. Install Dependencies

```bash
pip install -r requirements.txt
```

### 6. Run the Application

```bash
python app.py
```

### 7. Open in Browser

Visit:

```text
http://127.0.0.1:5000
```

## 🧠 AI and CSP Approach

The timetable generator uses the Constraint Satisfaction Problem approach.

A CSP consists of:

- **Variables:** Scheduling entities that need assignments.
- **Domains:** Possible values available for each variable.
- **Constraints:** Rules that valid timetable assignments must satisfy.

The solver uses techniques such as:

1. Backtracking Search
2. Minimum Remaining Values (MRV)
3. Forward Checking
4. Constraint Propagation
5. Local Search Optimization

These techniques help the system find valid timetable arrangements while reducing conflicts and improving the search process.

## 📊 Performance Evaluation

The CSP solver supports comparison of different scheduling strategies using performance metrics such as:

- Execution time
- Number of search nodes
- Backtracking activity
- Constraint violations
- Scheduling cost

## 🔮 Future Improvements

- Integration of more advanced optimization algorithms.
- Improved timetable visualization.
- Support for larger universities and departments.
- Additional scheduling constraints.
- Deployment as a cloud-based application.

## 👨‍💻 Project Information

**Project Name:** AI-Based University Timetable Generator  
**Domain:** Artificial Intelligence  
**Approach:** Constraint Satisfaction Problem (CSP)  
**Backend:** Python and Flask  
**Database:** SQLite

## 📜 License

This project is intended for educational and academic purposes.
