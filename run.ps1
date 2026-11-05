Write-Host "===================================================" -ForegroundColor Magenta
Write-Host " [Brand Veloura] Starting Development Server..." -ForegroundColor Green
Write-Host " Store Front:   http://127.0.0.1:8000/" -ForegroundColor Cyan
Write-Host " Admin Panel:   http://127.0.0.1:8000/admin/" -ForegroundColor Yellow
Write-Host " Admin Login:   admin / admin123456" -ForegroundColor White
Write-Host "===================================================" -ForegroundColor Magenta

python manage.py runserver 127.0.0.1:8000

