# user_admin/views.py
import logging
import threading

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy, reverse
from django.views.generic import (
    TemplateView,
    ListView,
    DetailView,
    DeleteView,
    UpdateView,
    View,
    FormView,
)
from django.utils.decorators import method_decorator
from django.conf import settings
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.db.models import Sum
from django.db import transaction
from django.contrib import messages

from users.models import User, UserWallet
from app.models import Withdraw, Deposit, Notification
from app.utils import create_notification
from .decorators import login_required
from .forms import AdminEmailForm, AddRemoveFundsForm

logger = logging.getLogger(__name__)


def send_mail_async(
    subject: str, message: str, from_email: str, recipient_list: list, **kwargs
):
    """
    Fire-and-forget wrapper for django.core.mail.send_mail.
    kwargs forwarded to send_mail (e.g. fail_silently, html_message).
    """

    def _worker():
        try:
            send_mail(subject, message, from_email, recipient_list, **kwargs)
        except Exception:
            logger.exception("Async send_mail failed")

    try:
        threading.Thread(target=_worker, daemon=True).start()
    except Exception:
        logger.exception("Failed to start send_mail thread")


def send_message_async(email_message):
    """
    Fire-and-forget wrapper for EmailMessage / EmailMultiAlternatives objects.
    Accepts an instance with a .send() method.
    """

    def _worker():
        try:
            email_message.send()
        except Exception:
            logger.exception("Async EmailMessage.send() failed")

    try:
        threading.Thread(target=_worker, daemon=True).start()
    except Exception:
        logger.exception("Failed to start EmailMessage send thread")


def update_user_status(user_id, status):
    user = User.objects.get(id=user_id)
    user.is_active = status
    user.save()


@method_decorator(login_required, name="dispatch")
class DashboardView(TemplateView):
    template_name = "user_admin/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = UserWallet.objects.values("currency").annotate(
            total_balance=Sum("balance")
        )

        balances = {w["currency"]: w["total_balance"] for w in qs}

        btc = balances.get("BTC", 0) or 0
        eth = balances.get("ETH", 0) or 0
        usdt = balances.get("USDT", 0) or 0
        ltc = balances.get("LTC", 0) or 0

        ctx["wallet_balances"] = balances
        ctx["total_balance"] = btc + eth + usdt + ltc
        ctx["btc_balance"] = btc
        ctx["eth_balance"] = eth
        ctx["usdt_balance"] = usdt
        ctx["ltc_balance"] = ltc
        ctx["deposits"] = Deposit.objects.order_by("-date_created")[:5]
        return ctx


@method_decorator(login_required, name="dispatch")
class ProfileView(View):
    def get(self, request, *args, **kwargs):
        return render(request, "user_admin/profile.html")

    def post(self, request, *args, **kwargs):
        firstName = request.POST.get("firstName")
        lastName = request.POST.get("lastName")
        address = request.POST.get("address")
        country = request.POST.get("country")

        User.objects.filter(email=request.user.email).update(
            first_name=firstName, last_name=lastName, address=address, country=country
        )
        return redirect(reverse("admin:profile"))


@method_decorator(login_required, name="dispatch")
class UserListView(ListView):
    model = User
    template_name = "user_admin/user/user_list.html"
    context_object_name = "users"

    def get_queryset(self):
        return User.objects.filter(is_superuser=False, is_staff=False)


@login_required
def mark_user_as_active(request, user_id):
    update_user_status(user_id, True)
    return redirect("admin:user-list")


@login_required
def mark_user_as_suspended(request, user_id):
    update_user_status(user_id, False)
    return redirect("admin:user-list")


@method_decorator(login_required, name="dispatch")
class UserDetailsView(DetailView):
    model = User
    template_name = "user_admin/user/user_details.html"
    context_object_name = "user"


@method_decorator(login_required, name="dispatch")
class UserDeleteView(DeleteView):
    model = User
    template_name = "user_admin/user/user_confirm_delete.html"
    success_url = reverse_lazy("user_admin:user-list")


@method_decorator(login_required, name="dispatch")
class UserWalletListView(ListView):
    model = UserWallet
    template_name = "user_admin/user_balance/user_balance_list.html"
    context_object_name = "user_balances"


@method_decorator(login_required, name="dispatch")
class UserWalletDetailsView(DetailView):
    model = UserWallet
    template_name = "user_admin/user_balance/user_balance_details.html"
    context_object_name = "user_balance"


@method_decorator(login_required, name="dispatch")
class UserWalletUpdateView(UpdateView):
    model = UserWallet
    template_name = "user_admin/user_balance/user_balance_form.html"
    fields = ["balance"]
    success_url = reverse_lazy("user_admin:user-balance-list")


@method_decorator(login_required, name="dispatch")
class UserWalletDeleteView(DeleteView):
    model = UserWallet
    template_name = "user_admin/user_balance/user_balance_confirm_delete.html"
    success_url = reverse_lazy("user_admin:user-balance-list")


def manage_user_funds(request, pk):
    user_balance = get_object_or_404(UserWallet, pk=pk)

    if request.method == "POST":
        form = AddRemoveFundsForm(request.POST)

        if form.is_valid():
            amount = form.cleaned_data["amount"]
            action = form.cleaned_data["action"]

            if action == "add":
                user_balance.balance += amount
                messages.success(
                    request,
                    f"{amount} added to the user balance. New balance: {user_balance.balance}",
                )
            elif action == "remove" and user_balance.balance >= amount:
                user_balance.balance -= amount
                messages.success(
                    request,
                    f"{amount} removed from the user balance. New balance: {user_balance.balance}",
                )
            else:
                messages.error(request, "Insufficient funds to remove.")

            user_balance.save()
            return redirect("admin:user-wallet-details", user_balance.id)
    else:
        form = AddRemoveFundsForm()

    return render(
        request,
        "user_admin/user_balance/manage_user_funds.html",
        {"form": form, "user_balance": user_balance},
    )


@method_decorator(login_required, name="dispatch")
class DepositListView(ListView):
    model = Deposit
    template_name = "user_admin/deposit/deposit_list.html"
    context_object_name = "deposits"


@method_decorator(login_required, name="dispatch")
class DepositDetailView(DetailView):
    model = Deposit
    template_name = "user_admin/deposit/deposit_detail.html"
    context_object_name = "deposit"


@method_decorator(login_required, name="dispatch")
class DepositUpdateView(UpdateView):
    model = Deposit
    template_name = "user_admin/deposit/deposit_form.html"
    fields = ["status"]

    def form_valid(self, form):
        # Save deposit and set self.object so later code can safely reference it
        deposit = form.save(commit=False)
        deposit.save()
        self.object = deposit

        mapping = {
            "Bitcoin": "BTC",
            "Ethereum": "ETH",
            "USDT": "USDT",
            "Litecoin": "LTC",
        }
        code = mapping.get(deposit.crypto_currency, deposit.crypto_currency)

        wallet = get_object_or_404(UserWallet, user=deposit.user, currency=code)
        wallet.balance += deposit.amount
        wallet.save()

        # Send email notification (async)
        send_mail_async(
            "Deposit Successfully Confirmed by Admin",
            "The transaction has been successfully confirmed by the admin.",
            settings.DEFAULT_EMAIL,
            [deposit.user.email],
            fail_silently=True,
        )

        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("admin:deposits")


@method_decorator(login_required, name="dispatch")
class DepositDeleteView(DeleteView):
    model = Deposit
    template_name = "user_admin/deposit/deposit_confirm_delete.html"
    success_url = reverse_lazy("admin:deposits")


@method_decorator(login_required, name="dispatch")
class WithdrawListView(ListView):
    model = Withdraw
    template_name = "user_admin/withdraw/withdraw_list.html"
    context_object_name = "withdrawals"


@method_decorator(login_required, name="dispatch")
class WithdrawDetailView(DetailView):
    model = Withdraw
    template_name = "user_admin/withdraw/withdraw_detail.html"
    context_object_name = "withdraw"


@method_decorator(login_required, name="dispatch")
class WithdrawUpdateView(UpdateView):
    model = Withdraw
    template_name = "user_admin/withdraw/withdraw_form.html"
    fields = ["status"]

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        previous_status = self.object.status
        new_status = request.POST.get("status")

        wallet = get_object_or_404(
            UserWallet, user=self.object.user, currency=self.object.wallet.currency
        )

        with transaction.atomic():
            self.object.status = new_status
            self.object.save()

            if new_status == "Approved" and previous_status == "Pending":
                if wallet.balance >= self.object.amount:
                    wallet.balance -= self.object.amount
                    wallet.save()
                    create_notification(
                        user=self.object.user,
                        title="Withdrawal Approved",
                        description=f"Your withdrawal of ${self.object.amount} to {self.object.wallet_address} has been approved.",
                    )
                    messages.success(
                        request, "Withdrawal approved and balance deducted."
                    )

                    # Send email notification to user (async)
                    send_mail_async(
                        "Withdrawal Processed and Confirmed by Admin",
                        "Your transaction has been processed and confirmed by the admin.",
                        settings.DEFAULT_EMAIL,
                        [self.object.user.email],
                        fail_silently=True,
                    )

                else:
                    messages.error(
                        request, "Insufficient balance to approve this withdrawal."
                    )
                    return redirect("admin:withdrawal", pk=self.object.id)

        return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse_lazy("admin:withdrawal", args=[self.object.id])


@method_decorator(login_required, name="dispatch")
class WithdrawDeleteView(DeleteView):
    model = Withdraw
    template_name = "user_admin/withdraw/withdraw_confirm_delete.html"
    success_url = reverse_lazy("admin:withdrawals")


class AdminEmailView(FormView):
    template_name = "user_admin/admin_email_form.html"
    form_class = AdminEmailForm
    success_url = reverse_lazy("admin:compose-mail")

    @method_decorator(login_required)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def form_valid(self, form):
        subject = form.cleaned_data["subject"]
        message = form.cleaned_data["message"]
        recipient_email = form.cleaned_data["recipient"]

        if recipient_email == "all":
            recipients = list(
                User.objects.filter(is_superuser=False, is_staff=False).values_list(
                    "email", flat=True
                )
            )
        else:
            recipients = [recipient_email]

        context = {
            "user": self.request.user,
            "subject": subject,
            "message": message,
        }

        html_message = render_to_string("user_admin/email_template.html", context)

        email = EmailMultiAlternatives(
            subject=subject,
            body=message,
            from_email=settings.DEFAULT_EMAIL,
            to=recipients,
        )
        email.attach_alternative(html_message, "text/html")

        # send using async wrapper
        send_message_async(email)

        messages.success(self.request, "Email sent successfully!")
        return super().form_valid(form)


@method_decorator(login_required, name="dispatch")
class NotificationsListView(ListView):
    model = Notification
    template_name = "user_admin/notifications.html"
    context_object_name = "notifications"
