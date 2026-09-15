# 🌐 STEM Sphere — Official Website

Welcome to the official repository for the **STEM Sphere** website.  

STEM Sphere is a student-led academic initiative dedicated to delivering high-quality **STEM enrichment**, **AP/ACT/SAT preparation**, and **college consulting**—designed by top-performing students for the next generation of scholars.

---

## 🎯 Mission

Our mission is to:

- Expand access to rigorous STEM education  
- Provide affordable 1-on-1 and small group tutoring in advanced STEM subjects  
- Guide students through scholarships, financial planning, and college admissions  
- Empower motivated learners to reach top-tier universities  
- Build a supportive community of curious, ambitious students  

---

## 🚀 About This Repository

This repository contains the source code for the **STEM Sphere Streamlit Website**, including:

- Homepage and program descriptions  
- Interactive service pages (tutoring, AP subjects, ACT/SAT prep)  
- College consulting info  
- Contact + intake forms  
- Branding elements and UI components  

The website will serve as the central hub for our students, parents, and partners.

---

## 🛠️ Tech Stack

**Primary technologies:**

- **Python 3.10+**
- **Streamlit** (web app framework)
- **Git & GitHub**
- **Visual Studio Code**

---

---

## 🧪 NMRx 2.0 Research Backend

`nmrx2/` holds the NMRx computational chemistry backend: a FastAPI service over
PySCF electronic structure, GIAO NMR shielding, finite-difference harmonic IR,
RDKit molecule preparation, AutoDock Vina docking, a persistent job queue, and a
conformal calibration layer that converts computed shieldings into chemical
shifts with a distribution-free coverage guarantee and an explicit abstention
rule.

- Backend overview and setup: [`nmrx2/README.md`](nmrx2/README.md)
- Calibration math, measured coverage and abstention rules: [`nmrx2/docs/CALIBRATION.md`](nmrx2/docs/CALIBRATION.md)
- Science scope and limits: [`nmrx2/docs/SCIENCE.md`](nmrx2/docs/SCIENCE.md)

It is a separate Python package with its own dependencies and does not affect the
Streamlit site in `app.py`.
