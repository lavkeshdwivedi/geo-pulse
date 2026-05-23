package com.lavkesh.geopulse;

import android.os.Bundle;
import com.getcapacitor.BridgeActivity;
import com.google.firebase.messaging.FirebaseMessaging;

public class MainActivity extends BridgeActivity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // Subscribe to the newsletter topic so CI can push notifications to all installs
        FirebaseMessaging.getInstance().subscribeToTopic("newsletter");
    }
}
