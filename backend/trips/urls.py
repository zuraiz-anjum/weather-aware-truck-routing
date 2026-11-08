from django.urls import path

from .views import HealthView, PlacesView, PlanView

urlpatterns = [
    path("plan/", PlanView.as_view()),
    path("places/", PlacesView.as_view()),
    path("health/", HealthView.as_view()),
]
