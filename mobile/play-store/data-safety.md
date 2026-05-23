# Data Safety form answers

Fill this in under **App content → Data safety** in Play Console.

## Data collection and sharing

Does your app collect or share any of the required user data types? **Yes** (only the FCM token, which counts as a device identifier when used for messaging).

Is all of the user data collected by your app encrypted in transit? **Yes** (HTTPS for the news feed, encrypted by FCM for push tokens).

Do you provide a way for users to request that their data is deleted? **Yes** (uninstalling the app removes the FCM token. Users may also email shiveshsolutions@gmail.com to request token deletion, though no profile is stored server side).

## Data types

App activity → none collected.
App info and performance → none collected.
Device or other IDs → **Device or other IDs (FCM registration token)** collected and shared with Google (Firebase Cloud Messaging). Purpose: app functionality (delivering new edition notifications). Not used for ads. Not used for analytics. Optional for the user. Encrypted in transit.
Personal info → none collected.
Financial info → none collected.
Health and fitness → none collected.
Messages → none collected.
Photos and videos → none collected.
Audio files → none collected.
Files and docs → none collected.
Calendar → none collected.
Contacts → none collected.
Location → none collected.
Web browsing → none collected.
Other → none collected.

## Security practices

Data is encrypted in transit. Users can request data deletion. App follows Google Play Families Policy if targeting children (we do not target children, so this is not applicable).
