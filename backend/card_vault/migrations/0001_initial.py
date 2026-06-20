# Generated for the Gerg Card Vault scaffold.

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CardVaultLocation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("description", models.TextField(blank=True)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="children",
                        to="card_vault.cardvaultlocation",
                    ),
                ),
            ],
            options={"ordering": ["sort_order", "name"]},
        ),
        migrations.CreateModel(
            name="CardVaultIntakeSession",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "session_type",
                    models.CharField(
                        choices=[("batch_front_back", "Batch front/back")],
                        db_index=True,
                        default="batch_front_back",
                        max_length=64,
                    ),
                ),
                ("title", models.CharField(blank=True, max_length=255)),
                ("sport", models.CharField(default="basketball", max_length=64)),
                ("expected_card_count", models.PositiveSmallIntegerField(default=10)),
                ("detected_front_count", models.PositiveSmallIntegerField(default=0)),
                ("detected_back_count", models.PositiveSmallIntegerField(default=0)),
                (
                    "review_status",
                    models.CharField(
                        choices=[
                            ("needs_review", "Needs review"),
                            ("in_review", "In review"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                        ],
                        db_index=True,
                        default="needs_review",
                        max_length=32,
                    ),
                ),
                ("extraction_status", models.CharField(db_index=True, default="not_started", max_length=64)),
                ("extraction_summary", models.JSONField(blank=True, default=dict)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="card_vault_intake_sessions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="CardVaultCard",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("slot_index", models.PositiveSmallIntegerField(db_index=True, default=1)),
                ("player_name", models.CharField(blank=True, max_length=255)),
                ("team", models.CharField(blank=True, max_length=255)),
                ("league", models.CharField(blank=True, max_length=64)),
                ("sport", models.CharField(default="basketball", max_length=64)),
                ("year", models.CharField(blank=True, max_length=32)),
                ("brand", models.CharField(blank=True, max_length=128)),
                ("product", models.CharField(blank=True, max_length=128)),
                ("set_name", models.CharField(blank=True, max_length=255)),
                ("card_number", models.CharField(blank=True, max_length=64)),
                ("rookie_status", models.BooleanField(default=False)),
                ("insert_name", models.CharField(blank=True, max_length=255)),
                ("parallel_name", models.CharField(blank=True, max_length=255)),
                ("serial_number", models.CharField(blank=True, max_length=64)),
                ("serial_total", models.CharField(blank=True, max_length=64)),
                ("autograph_detected", models.BooleanField(default=False)),
                ("relic_detected", models.BooleanField(default=False)),
                ("patch_detected", models.BooleanField(default=False)),
                ("estimated_raw_value", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ("storage_recommendation", models.TextField(blank=True)),
                ("extracted_json", models.JSONField(blank=True, default=dict)),
                ("confidence", models.FloatField(default=0)),
                (
                    "review_status",
                    models.CharField(
                        choices=[
                            ("needs_review", "Needs review"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                        ],
                        db_index=True,
                        default="needs_review",
                        max_length=32,
                    ),
                ),
                ("is_draft", models.BooleanField(db_index=True, default=True)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "approved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="approved_card_vault_cards",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "location",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="cards",
                        to="card_vault.cardvaultlocation",
                    ),
                ),
                (
                    "session",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="cards",
                        to="card_vault.cardvaultintakesession",
                    ),
                ),
            ],
            options={"ordering": ["-created_at", "slot_index"]},
        ),
        migrations.CreateModel(
            name="CardVaultImage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("front_group_original", "Front group original"),
                            ("back_group_original", "Back group original"),
                            ("front_crop", "Front crop"),
                            ("back_crop", "Back crop"),
                        ],
                        db_index=True,
                        max_length=64,
                    ),
                ),
                ("image", models.FileField(upload_to="card_vault/%Y/%m/%d/")),
                ("original_filename", models.CharField(blank=True, max_length=512)),
                ("slot_index", models.PositiveSmallIntegerField(blank=True, db_index=True, null=True)),
                (
                    "crop_box",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="Future crop geometry, e.g. {'x': 0, 'y': 0, 'width': 0, 'height': 0}.",
                    ),
                ),
                ("detection_confidence", models.FloatField(default=0)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "card",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="images",
                        to="card_vault.cardvaultcard",
                    ),
                ),
                (
                    "session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="images",
                        to="card_vault.cardvaultintakesession",
                    ),
                ),
            ],
            options={"ordering": ["session", "role", "slot_index", "id"]},
        ),
        migrations.AddField(
            model_name="cardvaultcard",
            name="back_image_crop",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="back_for_cards",
                to="card_vault.cardvaultimage",
            ),
        ),
        migrations.AddField(
            model_name="cardvaultcard",
            name="front_image_crop",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="front_for_cards",
                to="card_vault.cardvaultimage",
            ),
        ),
        migrations.CreateModel(
            name="CardVaultValuation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source", models.CharField(max_length=128)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=10)),
                ("currency", models.CharField(default="USD", max_length=8)),
                ("confidence", models.FloatField(default=0)),
                ("valuation_date", models.DateField(blank=True, null=True)),
                ("raw_data", models.JSONField(blank=True, default=dict)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "card",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="valuations",
                        to="card_vault.cardvaultcard",
                    ),
                ),
            ],
            options={"ordering": ["-valuation_date", "-created_at"]},
        ),
        migrations.AddIndex(
            model_name="cardvaultintakesession",
            index=models.Index(fields=["session_type", "review_status"], name="cv_session_type_status_idx"),
        ),
        migrations.AddIndex(
            model_name="cardvaultintakesession",
            index=models.Index(fields=["created_by", "-created_at"], name="cv_session_user_created_idx"),
        ),
        migrations.AddIndex(
            model_name="cardvaultcard",
            index=models.Index(fields=["review_status", "is_draft"], name="cv_card_review_draft_idx"),
        ),
        migrations.AddIndex(
            model_name="cardvaultcard",
            index=models.Index(fields=["session", "slot_index"], name="cv_card_session_slot_idx"),
        ),
        migrations.AddConstraint(
            model_name="cardvaultcard",
            constraint=models.UniqueConstraint(fields=("session", "slot_index"), name="card_vault_unique_session_slot"),
        ),
        migrations.AddIndex(
            model_name="cardvaultimage",
            index=models.Index(fields=["session", "role"], name="cv_image_session_role_idx"),
        ),
        migrations.AddIndex(
            model_name="cardvaultimage",
            index=models.Index(fields=["session", "slot_index"], name="cv_image_session_slot_idx"),
        ),
    ]
