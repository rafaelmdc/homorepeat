from __future__ import annotations

from django import forms


class ImportRunForm(forms.Form):
    detected_publish_root = forms.ChoiceField(required=False)
    publish_root = forms.CharField(
        required=False,
        max_length=500,
        label="Manual publish root",
        widget=forms.TextInput(
            attrs={
                "placeholder": "/app/runs/<run-id>/publish",
            }
        ),
    )
    replace_existing = forms.BooleanField(required=False)

    def __init__(self, *args, detected_publish_runs=None, **kwargs):
        super().__init__(*args, **kwargs)
        publish_runs = list(detected_publish_runs or [])
        self.fields["detected_publish_root"].label = "Detected published run"
        self.fields["detected_publish_root"].choices = [("", "Choose a detected publish root")] + [
            (run.publish_root, f"{run.run_id} [{run.label}]")
            for run in publish_runs
        ]
        self.fields["detected_publish_root"].widget.attrs["class"] = "form-select"
        self.fields["publish_root"].widget.attrs["class"] = "form-control"
        self.fields["replace_existing"].widget.attrs["class"] = "form-check-input"

    def clean(self):
        cleaned_data = super().clean()
        detected_publish_root = (cleaned_data.get("detected_publish_root") or "").strip()
        publish_root = (cleaned_data.get("publish_root") or "").strip()
        resolved_publish_root = publish_root or detected_publish_root
        if not resolved_publish_root:
            raise forms.ValidationError(
                "Choose a detected publish root or enter one manually."
            )
        cleaned_data["resolved_publish_root"] = resolved_publish_root
        cleaned_data["publish_root"] = publish_root
        cleaned_data["detected_publish_root"] = detected_publish_root
        return cleaned_data
