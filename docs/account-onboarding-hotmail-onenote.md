# Hotmail and future OneNote account onboarding

**Audience:** Lee (the account owner)  
**Current state:** Hotmail is a disabled configuration scaffold. `lee-kb` has
an Outlook connector, but it does **not** currently implement a OneNote
connector. Do not treat this guide as evidence that OneNote ingestion is
available.

## 1. Give `lee-kb` delegated consent for Hotmail

This is an interactive, one-time consent operation. It does not run a Graph
sync and it does not put a token in this repository or in TOML. The CLI stores
the account's token in its configured OS-protected token store.

### 1.1 Confirm the app registration before signing in

The public/native Microsoft Entra app used for this account must have:

- **Supported account types:** `Accounts in any organizational directory AND
  personal Microsoft accounts` (not “Personal Microsoft accounts only”);
- **Public client/native** platform;
- device-code flow enabled (`allowPublicClient`);
- no client secret (this is a public client); and
- only delegated read scopes needed for the source. For the current Outlook
  connector these are `Mail.Read` and `User.Read`.

The current `lee-kb` Graph runtime accepts exactly `Mail.Read` plus `User.Read`
for Outlook. It does not accept an app-only grant or an arbitrary `.All`
scope.

### 1.2 Enable only the account block

Make a copy of the live file before editing it. The dated backup made for this
change is:

```text
~/.config/lee-kb/config.toml.bak-2026-08-10
```

In `~/.config/lee-kb/config.toml`, uncomment this block from the
Hotmail scaffold:

```toml
[microsoft_graph.accounts.hotmail]
user_id = "leebase@hotmail.com"
tenant = "common"
scopes = ["Mail.Read", "User.Read"]
```

Leave `[outlook.hotmail_inbox]` commented until a real Hotmail Inbox folder ID
has been obtained. The account block is sufficient for authentication; the
placeholder folder ID in the disabled source block must never be used for a
sync.

### 1.3 Run the exact authentication command

From any directory, run:

```bash
lee-kb auth login --account hotmail --config ~/.config/lee-kb/config.toml
```

`--account` selects the local account namespace
`microsoft_graph.accounts.hotmail`. The command uses Microsoft's device
authorization flow. When it prints a verification URL and one-time code:

1. Open the printed URL in a browser.
2. Enter the printed code.
3. Sign in as **`leebase@hotmail.com`**, not as the `lee@leebase.com` identity.
4. Review and accept the requested delegated permissions.
5. Wait for the terminal to print `Authenticated Microsoft Graph account
   hotmail.`

`lee-kb` verifies the provider identity returned by `/me` against
`leebase@hotmail.com` before retaining the grant. If the identity is wrong,
stop and revoke the local grant rather than continuing:

```bash
lee-kb auth revoke --account hotmail --config ~/.config/lee-kb/config.toml
```

No OneNote permission is requested by this Hotmail Outlook scaffold. A
successful login is consent only; it is not a full Graph sync.

### 1.4 Optional future Outlook source activation

Only after consent and after obtaining the target Inbox's actual Graph folder
ID, uncomment and complete the source block. The key names are the ones
implemented by `src/lee_kb/main.py`:

```toml
[outlook.hotmail_inbox]
account = "hotmail"
mailbox_owner = "leebase@hotmail.com"
folder_id = "<actual-Hotmail-Inbox-folder-id>"
folder_name = "Inbox"
project = "default"
allowed_principals = ["employee:employee-zero"]
```

Do not guess `folder_id`, owner, account ID, or principal. The account ID is
`hotmail`; the provider identity is `leebase@hotmail.com`; and the source is
read-only. Run a normal configuration/load check before any sync. A full Graph
sync is intentionally outside this onboarding step.

## 2. Future OneNote connection (not implemented yet)

There is currently no OneNote connector, OneNote configuration section, or
OneNote sync command in `lee-kb`. Do not add a speculative `[onenote]` section
or run the current Outlook login with `Notes.Read`: the current Graph runtime
allows only the exact Outlook or Calendar read-only scope sets. These are the
requirements for the future implementation and its consent operation.

### 2.1 Register a public client once

Lee must do this in a browser at <https://entra.microsoft.com>:

1. Open **App registrations** and choose **New registration**.
2. Set **Supported account types** to **Accounts in any organizational
   directory AND personal Microsoft accounts**. Do not select “Personal
   Microsoft accounts only”; that option causes a misleading first-party-app
   consent failure with device-code flow.
3. Configure a **Public client/native** platform.
4. Enable device-code flow (`allowPublicClient`).
5. Do not create a client secret. A public client using device code must not
   depend on one.
6. Add only the delegated permissions needed by the future read-only OneNote
   connector. For an MSA, the required scope set is exactly:

   ```text
   https://graph.microsoft.com/Notes.Read
   https://graph.microsoft.com/User.Read
   offline_access
   ```

   `offline_access` is required for a refresh token. Do **not** request
   application permissions, app-only access, or any `.All` scope: an MSA cannot
   consent to `.All` application scopes, and Graph rejects that pattern.

Record the resulting public client ID in the future account configuration only
when OneNote support exists. Never put a client secret or token in the config
file.

### 2.2 Consent per identity with device code

For each account that will be a OneNote source, perform one interactive device
code consent using that account's own local token namespace. In particular,
for Hotmail the future command will use the already established account ID:

```bash
lee-kb auth login --account hotmail --config ~/.config/lee-kb/config.toml
```

That command will be usable for OneNote only after the future OneNote support
adds the `Notes.Read`, `User.Read`, and `offline_access` delegated scope
boundary. Until then, the current command is Outlook-only and requests
`Mail.Read` plus `User.Read` as shown in section 1.

During the future OneNote consent:

- use device-code flow and sign in as the account being bound;
- keep one refresh-token record per account (`hotmail` must not reuse the
  `personal` token namespace);
- do not inspect or reject a token merely because an MSA access token is not a
  JWT; and
- keep the connector read-only. OneNote table `PATCH` behavior is broken on
  consumer tenants, so the future source must not depend on writes.

The future implementation must also prove a safe polling/checkpoint strategy
before claiming incremental OneNote synchronization. OneNote has no currently
implemented `lee-kb` connector in this repository.

## 3. Stop conditions

Stop and ask Lee to review the app registration or consent if any of the
following occurs:

- Microsoft asks for an application permission or a `.All` scope;
- the signed-in identity is not the account named in the account block;
- the app registration is not a public client with device-code flow enabled;
- the terminal does not verify the expected `/me` identity; or
- a proposed OneNote change requires a client secret, app-only auth, or a
  write operation.
