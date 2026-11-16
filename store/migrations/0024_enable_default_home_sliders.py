from django.db import migrations

def enable_default_home_sliders(apps, schema_editor):
    Category = apps.get_model('store', 'Category')
    # تفعيل أشرطة الأقسام الرئيسية الافتراضية لضمان عدم تأثر الصفحة الرئيسية بعد إضافة الحقل
    Category.objects.filter(category_type='perfumes', parent__isnull=True).update(show_in_home_slider=True, home_slider_order=1)
    Category.objects.filter(category_type='watches', parent__isnull=True).update(show_in_home_slider=True, home_slider_order=2)
    Category.objects.filter(category_type__in=['cosmetics', 'care'], parent__isnull=True).update(show_in_home_slider=True, home_slider_order=3)

def reverse_default_home_sliders(apps, schema_editor):
    pass

class Migration(migrations.Migration):

    dependencies = [
        ('store', '0023_category_home_slider_order_and_more'),
    ]

    operations = [
        migrations.RunPython(enable_default_home_sliders, reverse_default_home_sliders),
    ]
