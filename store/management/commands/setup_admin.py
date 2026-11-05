import os
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User


class Command(BaseCommand):
    help = 'إنشاء أو تحديث حساب مدير النظام (Admin Superuser) في بيئة الإنتاج السحابية'

    def add_arguments(self, parser):
        parser.add_argument('--username', type=str, default=None, help='اسم مستخدم المدير')
        parser.add_argument('--email', type=str, default=None, help='البريد الإلكتروني')
        parser.add_argument('--password', type=str, default=None, help='كلمة المرور')

    def handle(self, *args, **options):
        username = options.get('username') or os.getenv('DJANGO_SUPERUSER_USERNAME')
        email = options.get('email') or os.getenv('DJANGO_SUPERUSER_EMAIL') or 'admin@brandveloura.com'
        password = options.get('password') or os.getenv('DJANGO_SUPERUSER_PASSWORD')

        if not username:
            self.stdout.write(self.style.WARNING('يرجى تحديد اسم المستخدم للمدير:'))
            username = input('اسم المستخدم [admin]: ').strip() or 'admin'

        if not password:
            self.stdout.write(self.style.WARNING('يرجى إدخال كلمة المرور للمدير:'))
            password = input('كلمة المرور: ').strip()

        if not password:
            self.stdout.write(self.style.ERROR('خطأ: لا يمكن ترك كلمة المرور فارغة.'))
            return

        user = User.objects.filter(username=username).first()
        if user:
            user.set_password(password)
            user.email = email
            user.is_staff = True
            user.is_superuser = True
            user.is_active = True
            user.save()
            self.stdout.write(self.style.SUCCESS(f'[OK] تم تحديث حساب المدير بنجاح: {username}'))
        else:
            User.objects.create_superuser(username=username, email=email, password=password)
            self.stdout.write(self.style.SUCCESS(f'[OK] تم إنشاء حساب مدير جديد بنجاح: {username}'))

