# Troubleshooting FAQ

## Login Issues

If you cannot log in, first verify that you are using the correct email address and password. Try resetting your password using the "Forgot Password" link. If you have MFA enabled, ensure your authenticator app is synced with the correct time. Clear your browser cache and cookies, then try again. If the issue persists, contact support.

## MFA Problems

If your MFA codes are not working, check that your device clock is accurate — time drift of more than 30 seconds can cause code verification to fail. If you have lost access to your authenticator app, use one of your backup recovery codes to log in. If you have no recovery codes, contact support with your account email for identity verification.

## Password Reset Email Not Received

If you did not receive a password reset email, check your spam or junk folder. Verify that you entered the correct email address. Some email providers may delay delivery by up to 15 minutes. If you still have not received the email after 15 minutes, try requesting a new reset link or contact support.

## Slow Dashboard Performance

Dashboard loading slowly can be caused by large data sets, browser extensions, or network issues. Try disabling browser extensions, clearing your cache, or using a different browser. If the dashboard is consistently slow, check our status page for any ongoing incidents. Pro and Enterprise users can enable dashboard data caching from Settings > Performance.

## Data Export Stuck

If your data export is stuck or not completing, it may be due to a large dataset exceeding memory limits. Try exporting a smaller date range or fewer data types. If the export has been processing for more than 30 minutes, cancel it and try again. Contact support if the issue persists.

## Integration Errors

Common integration errors include SSO configuration mismatches, expired certificates, and incorrect callback URLs. For SSO issues, verify that your Identity Provider metadata URL is correct and the signing certificate has not expired. For OAuth integrations, ensure the redirect URI matches exactly, including trailing slashes.

## Data Sync Delays

Real-time data sync has a maximum delay of 5 seconds under normal conditions. If you notice longer delays, check your webhook endpoint response times. Endpoints that respond slowly or timeout can cause cascading delays. Check the Sync Status dashboard in Settings > Integrations for real-time sync health metrics.

## Browser Compatibility

Our application supports the latest two versions of Chrome, Firefox, Safari, and Edge. If you experience rendering issues, ensure your browser is up to date. Internet Explorer is not supported. For the best experience, we recommend using Chrome or Firefox with JavaScript enabled.
