from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model


class GergVaultSignupForm(UserCreationForm):
    email = forms.EmailField(required=True, help_text="Used for password reset and account verification.")

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username", "email")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user
