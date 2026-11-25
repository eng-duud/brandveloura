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
        force_reset = os.getenv('FORCE_SUPERUSER_PASSWORD_RESET', 'False').lower() in ('true', '1') or bool(options.get('password'))
        if user:
            updated_fields = []
            if not user.is_staff:
                user.is_staff = True
                updated_fields.append('is_staff')
            if not user.is_superuser:
                user.is_superuser = True
                updated_fields.append('is_superuser')
            if not user.is_active:
                user.is_active = True
                updated_fields.append('is_active')
            if email and not user.email:
                user.email = email
                updated_fields.append('email')
            if force_reset:
                user.set_password(password)
                updated_fields.append('password')
            if updated_fields:
                user.save(update_fields=updated_fields)
            self.stdout.write(self.style.SUCCESS(f'[OK] حساب المدير جاهز ومفعل: {username}'))
        else:
            User.objects.create_superuser(username=username, email=email, password=password)
            self.stdout.write(self.style.SUCCESS(f'[OK] تم إنشاء حساب مدير جديد بنجاح: {username}'))

