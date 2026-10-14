# Setting up real accounts in MomSakhi

Follow these steps to enable real Google sign-in and live shared posts (Real Mode). It takes about 5 minutes and the free "Spark" plan is all you need.

1. Go to the [Firebase Console](https://console.firebase.google.com/) and create a new project (use your personal Google account, not your work account).
2. Click the Web icon (</>) to add a Firebase Web App to the project.
3. Copy the configuration object they give you into `firebase-config.js`. (Note: The web apiKey is not a secret; it's safe to commit).
4. Go to **Authentication** > **Sign-in method**, enable the **Google** provider, and save.
5. In Authentication > Settings > **Authorized domains**, add `momsakhi.com` (localhost is already there).
6. Go to **Firestore Database** and create a database (choose Production mode, and pick a US region).
7. Go to the **Rules** tab in Firestore, paste the contents of `firestore.rules` (from this repository) into the editor, and click **Publish**.
