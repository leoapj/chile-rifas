"""Formularios del panel de moderación (/moderar/)."""

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.utils.text import slugify

from .models import BankAccount, Payment, Raffle, SiteConfiguration

User = get_user_model()

DT_WIDGET = forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")


class StaffLoginForm(AuthenticationForm):
    """Solo deja entrar a personal autorizado (is_staff)."""

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_staff:
            raise forms.ValidationError("Esta cuenta no tiene acceso al panel de moderación.", code="no_staff")


class RaffleForm(forms.ModelForm):
    class Meta:
        model = Raffle
        fields = [
            "name", "slug", "description", "image", "organizer_name", "bank_accounts",
            "price_clp", "total_tickets", "status", "draw_date",
        ]
        widgets = {
            "bank_accounts": forms.CheckboxSelectMultiple,
            "description": forms.Textarea(attrs={"rows": 4}),
        }
        help_texts = {"slug": "Dirección de la rifa (se genera sola si lo dejas vacío)."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False
        self.fields["draw_date"].widget = DT_WIDGET
        self.fields["draw_date"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"]
        self.fields["bank_accounts"].queryset = BankAccount.objects.all()
        self.fields["bank_accounts"].label_from_instance = lambda a: f"{a} — {a.holder_name}"

    def clean_slug(self):
        slug = self.cleaned_data.get("slug") or slugify(self.data.get("name", ""))[:170]
        if not slug:
            raise forms.ValidationError("No se pudo generar la dirección; escríbela.")
        base, n = slug, 2
        while Raffle.objects.filter(slug=slug).exclude(pk=self.instance.pk).exists():
            slug, n = f"{base}-{n}", n + 1
        return slug

    def clean_total_tickets(self):
        total = self.cleaned_data["total_tickets"]
        if total < 1:
            raise forms.ValidationError("Debe haber al menos 1 número.")
        if self.instance.pk:
            blocked = self.instance.tickets.filter(number__gt=total).exclude(status="available")
            if blocked.exists():
                nums = list(blocked.values_list("number", flat=True)[:8])
                raise forms.ValidationError(f"No puedes bajar a {total}: los números {nums} ya tienen compradores.")
        return total


class BankAccountForm(forms.ModelForm):
    class Meta:
        model = BankAccount
        fields = ["bank_name", "account_type", "account_number", "holder_name", "holder_rut",
                  "notification_email", "is_active", "sort_order"]


class SiteConfigForm(forms.ModelForm):
    class Meta:
        model = SiteConfiguration
        fields = ["admin_notification_email", "contact_whatsapp", "promo_whatsapp", "ticket_reservation_minutes",
                  "proof_review_hours", "max_tickets_per_purchase"]


class PaymentEditForm(forms.ModelForm):
    """Corregir datos del comprador (p. ej. un correo mal escrito) y dejar notas internas."""

    class Meta:
        model = Payment
        fields = ["buyer_name", "buyer_phone", "buyer_email", "buyer_reference", "admin_notes"]
        widgets = {"admin_notes": forms.Textarea(attrs={"rows": 3})}


class ManualSaleForm(forms.Form):
    numbers = forms.CharField(label="Números", help_text="Ej. 5, 8, 20-25", max_length=500)
    buyer_name = forms.CharField(label="Nombre del comprador", max_length=150)
    buyer_phone = forms.CharField(label="Teléfono", max_length=30)
    buyer_email = forms.EmailField(label="Correo (opcional)", required=False)
    notes = forms.CharField(label="Notas (opcional)", required=False, widget=forms.Textarea(attrs={"rows": 2}))


class WinnerForm(forms.Form):
    number = forms.IntegerField(label="Número ganador (déjalo vacío para sortear al azar)", required=False, min_value=1)


class ModeratorCreateForm(forms.ModelForm):
    password = forms.CharField(label="Contraseña", widget=forms.PasswordInput, min_length=8,
                               help_text="Mínimo 8 caracteres. Compártesela a la persona por un canal seguro.")

    class Meta:
        model = User
        fields = ["username", "first_name", "email"]

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_staff = True
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


class PasswordResetForm(forms.Form):
    password = forms.CharField(label="Nueva contraseña", widget=forms.PasswordInput, min_length=8)
