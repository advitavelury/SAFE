import firebase_admin
from firebase_admin import credentials, firestore, storage
from pathlib import Path
cred = credentials.Certificate(
    Path(__file__).resolve().parent /
    "safe-ddacb-firebase-adminsdk-fbsvc-4c54ebf592.json"
    )
firebase_admin.initialize_app(cred, {
    "storageBucket": "safe-ddacb.firebasestorage.app"
})

production_db = firestore.client()
production_bucket = storage.bucket()