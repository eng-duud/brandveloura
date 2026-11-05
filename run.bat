@echo off
title Brand Veloura Luxury Store
echo ===================================================
echo [Brand Veloura] Starting Development Server...
echo Store Front:   http://127.0.0.1:8000/
echo Admin Panel:   http://127.0.0.1:8000/admin/
echo Admin Login:   admin / admin123456
echo ===================================================
python manage.py runserver 127.0.0.1:8000
pause

