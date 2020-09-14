import os
import uuid

from django.shortcuts import render, redirect, reverse
from django.conf import settings
from django.contrib.auth.models import User, Group
from django.contrib.auth import login
from django.utils.http import urlencode
from django.conf import settings

portal_password = os.environ.get("PORTAL_PASSWORD")

registration_type = os.environ.get("REGISTRATION_TYPE", "one-step")
enable_registration = os.environ.get("ENABLE_REGISTRATION", "true")
catalog_visibility = os.environ.get("CATALOG_VISIBILITY", "private")


def accounts_create(request):
    if request.user.is_authenticated:
        return redirect("workshops_catalog")

    if enable_registration != "true" or registration_type != "anonymous":
        return redirect("login")

    created = False

    while not created:
        username = uuid.uuid4()
        user, created = User.objects.get_or_create(username=username)

    group, _ = Group.objects.get_or_create(name="anonymous")

    user.groups.add(group)

    login(request, user, backend=settings.AUTHENTICATION_BACKENDS[0])

    return redirect("workshops_catalog")


def index(request):
    if portal_password:
        if not request.session.get("is_allowed_access_to_event"):
            return redirect(
                reverse("workshops_access")
                + "?"
                + urlencode({"redirect_url": reverse("index")})
            )

    if not request.user.is_authenticated:
        if registration_type == "anonymous":
            return redirect("accounts_create")
        elif catalog_visibility == "private":
            return redirect("login")

    return redirect("workshops_catalog")
