from django.shortcuts import render
from django.http import HttpResponse

def healthz(request):
    # Keep this as fast and cheap as possible.
    # Optionally check DB / redis here if you really need to.
    return HttpResponse("OK", status=200)

# Create your views here.
