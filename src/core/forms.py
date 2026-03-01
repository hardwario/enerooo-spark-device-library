"""Core forms."""

from django import forms
from django.contrib.auth.password_validation import validate_password

from .models import Invitation, User


class InvitationForm(forms.ModelForm):
    """Form for creating an invitation."""

    class Meta:
        model = Invitation
        fields = ["email", "role"]
        widgets = {
            "email": forms.EmailInput(attrs={"placeholder": "user@example.com"}),
        }


class AcceptInvitationForm(forms.Form):
    """Form for accepting an invitation and creating a user account."""

    username = forms.CharField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput)
    password_confirm = forms.CharField(label="Confirm password", widget=forms.PasswordInput)

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("This username is already taken.")
        return username

    def clean_password(self):
        password = self.cleaned_data["password"]
        validate_password(password)
        return password

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        password_confirm = cleaned_data.get("password_confirm")
        if password and password_confirm and password != password_confirm:
            self.add_error("password_confirm", "Passwords do not match.")
        return cleaned_data


class UserRoleForm(forms.ModelForm):
    """Form for updating a user's role and active status."""

    class Meta:
        model = User
        fields = ["role", "is_active"]
