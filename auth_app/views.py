# auth_app/views.py
import logging
import threading

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import LogoutView
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from .decorators import guest_only
from django.contrib import messages
from users.models import User
from django.views.generic import FormView

from .decorators import guest_only
from .forms import SignupForm, LoginForm
from users.models import User
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def send_mail_async(
    subject: str, message: str, from_email: str, recipient_list: list, **kwargs
):
    """
    Fire-and-forget send_mail: runs send_mail in a daemon thread so the
    request doesn't block on SMTP connection. Exceptions are logged.
    kwargs are forwarded to django.core.mail.send_mail (e.g. fail_silently, html_message).
    """

    def _worker():
        try:
            send_mail(subject, message, from_email, recipient_list, **kwargs)
        except Exception:
            logger.exception("Async email send failed")

    try:
        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
    except Exception:
        # Extremely unlikely to fail, but log it so we can investigate
        logger.exception("Failed to start email send thread")


@method_decorator(guest_only, name="dispatch")
class CustomLoginView(FormView):
    template_name = "registration/login.html"
    form_class = LoginForm
    success_url = reverse_lazy("user:dashboard")

    def get_success_url(self):
        user = self.request.user
        if user.is_superuser or user.is_staff:
            return reverse_lazy("admin:dashboard")
        return reverse_lazy("user:dashboard")

    def form_valid(self, form):
        email = form.cleaned_data["email"]
        password = form.cleaned_data["password"]
        user = User.objects.filter(email=email).first()

        if user and user.check_password(password):
            login(self.request, user)

            # Send login notification email in background thread
            send_mail_async(
                subject="New Login to Your Account, Was This You?",
                message="Your account was logged into. If this wasn't you, please contact support.",
                from_email=settings.DEFAULT_EMAIL,
                recipient_list=[email],
                fail_silently=True,
            )

            return super().form_valid(form)
        else:
            messages.error(self.request, "Invalid email or password")
            return self.form_invalid(form)


class SignupView(FormView):
    template_name = "registration/signup.html"
    form_class = SignupForm
    success_url = reverse_lazy("user:dashboard")

    def form_valid(self, form):
        user = form.save()
        login(self.request, user)

        # Send welcome email in background thread
        send_mail_async(
            subject="Welcome to OptionsTradezHub!",
            message="Thank you for joining OptionsTradezHub! We're excited to have you on board.",
            from_email=settings.DEFAULT_EMAIL,
            recipient_list=[user.email],
            fail_silently=True,
        )

        messages.success(self.request, "Registration successful")
        return super().form_valid(form)


class CustomLogoutView(LogoutView):
    next_page = reverse_lazy("auth:login")
