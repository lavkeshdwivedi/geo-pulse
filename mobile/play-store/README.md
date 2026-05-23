# GeoPulse Play Store submission kit

Everything you need to take GeoPulse from the internal track to public production. Files are grouped by what they map to in Play Console.

## Where things go

`listing.md` has the app name, short description, and full description. Copy them straight into Store presence, Main store listing.

`data-safety.md` is the script for App content, Data safety. Click through the wizard and pick the answer marked next to each question.

`content-rating.md` is the script for App content, Content ratings. Most answers are No. Expected rating is Everyone or PEGI 3.

`target-audience.md` is for App content, Target audience and content. Pick 18 and over.

`graphics/app-icon-512.png` is the 512x512 high res icon. Upload under Store presence, Main store listing, App icon.

`graphics/feature-graphic-1024x500.png` is the 1024x500 feature graphic. Upload under Store presence, Main store listing, Feature graphic.

`screenshots/phone-01.png` through `phone-06.png` are six 1080x2160 phone screenshots. Upload at least two under Store presence, Main store listing, Phone screenshots. Eight is the max.

## Privacy policy URL

https://pulse.lavkesh.com/privacy/

Paste this under Store presence, Main store listing, Privacy policy.

## Build that should ship with this listing

`mobile/android/app/build/outputs/bundle/release/app-release.aab` after you rebuild with versionCode 4. The version on the internal track (versionCode 3) has the notification bug. Do not promote that build to production.

## Rebuild and ship checklist

From `mobile/`:

```
npx cap sync android
cd android
gradlew.bat bundleRelease
```

Then upload the AAB from `mobile/android/app/build/outputs/bundle/release/app-release.aab` to the Internal testing track first. Open the app on your phone after the new build lands, accept the notification permission prompt, and wait for the next hourly newsletter to confirm a push lands. Once you have seen one push notification, promote the same build from Internal to Production in Play Console.

## What changed in versionCode 4

`AndroidManifest.xml` adds `POST_NOTIFICATIONS` so Android 13+ delivers FCM messages.

`www/app.js` and `android/app/src/main/assets/public/app.js` replace the dead `deviceready` listener with a `DOMContentLoaded` initializer, which actually fires under Capacitor 6. Push permission is now requested, the FCM token is logged, and the four notification listeners are registered properly.

`build.gradle` bumps `versionCode` to 4 and `versionName` to 1.0.1.

## Things you still do by hand in Play Console

App access. Pick "All functionality is available without special access" since GeoPulse needs no login.

Ads. Pick "No, my app does not contain ads".

Government apps. No.

News apps declaration. Yes, this is a news app. Confirm you have the legal right to publish the aggregated content (GeoPulse only summarises and links back, never republishes full text).

Tax and pricing. Free.

Countries. Available everywhere unless you want to exclude any.
