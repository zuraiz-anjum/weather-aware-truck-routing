from django.urls import include, path

urlpatterns = [
    path("api/", include("trips.urls")),
]

handler404 = "trips.views.not_found"
