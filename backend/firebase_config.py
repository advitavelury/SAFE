import firebase_admin
from firebase_admin import credentials, firestore, storage

cred = credentials.Certificate("safe-ddacb-firebase-adminsdk-fbsvc-4c54ebf592.json")
firebase_admin.initialize_app(cred)
firebase_admin.initialize_app(cred, {
    "storageBucket": "safe-ddacb.firebasestorage.app"
})

production_db = firestore.client()
production_bucket = storage.bucket()