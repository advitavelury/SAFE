# SAFE

**Smart Assisted Fall and Emergency**

Our FIT3161 / FIT3162 prototype detects possible falls and distress events using
YOLO and shows them in a React dashboard. It is a student project, not a validated
emergency system.

## Teammate quick start

**Run the dashboard and detection on your own laptop. No Vercel setup or tunnel needed.**

### First-time setup

**1. Get these ready**

- Python (3.11 recommended), Node.js with npm, and the SAFE repository.
- Your approved SAFE login. Both **admin and operator/staff** can run detection.
- The team's **public Firebase web configuration** for `safe-ddacb`.
- A **private Firebase service-account JSON file** for the same project, supplied securely.

Ask the project admin for the Firebase details and login approval. You do not need
to create another Firebase project or change its rules.

**2. Open SAFE in VS Code and open a terminal**

Run commands from the main SAFE folder, where `requirements.txt` is located.
Commit or safely preserve any unfinished code changes before switching branches.

```sh
git switch main
git pull --ff-only origin main
```

**3. Install the dependencies**

On **Mac/Linux**:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
npm ci --prefix front-end
```

On **Windows PowerShell**:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
npm ci --prefix front-end
```

If `.venv` already exists, skip creating it and activate it instead.

**4. Add your local configuration**

- In VS Code, duplicate `front-end/.env.example` and name the copy `.env` in
  the same folder. If `.env` already exists, update it instead.
- Fill in the `VITE_FIREBASE_...` values using the team's public web configuration.
  Keep `VITE_FIREBASE_INCIDENTS_COLLECTION=incidents`. Leave both API origin fields blank;
  the launcher connects them for you.
- Save the private service-account JSON **outside the SAFE folder**, for example
  in Downloads. Note its full file path for the next command.

**Never put the private JSON contents in `.env`, frontend code, Git or chat.**
Firebase Console access alone does not replace this backend credential file.

### Start the demo

With your virtual environment activated, run:

```sh
python scripts/run_demo.py --service-account "/full/path/to/your-key.json" --record
```

Replace the quoted path with your actual JSON file path. Keep the quotes if the
path contains spaces. On Windows, use a path such as `"C:\Users\YourName\Downloads\your-key.json"`.

**Open the dashboard URL printed in the terminal.** Keep that terminal open.
The launcher starts both React and the Python detector and chooses available ports.
Use this local URL, not the Vercel website, for your laptop's demo.

### Use the camera

1. Sign in, open **Monitor**, and click **Connect webcam**.
2. Allow camera access. Select your laptop camera if your phone camera is selected.
3. To save clips, tick **Record red events locally** before starting detection.
4. Click **Start detection**. A webcam preview by itself does not run detection.
5. Select **Detection frames** to see the pose and alerts. Keep the full body visible.
6. After a red event, leave detection running for five more seconds. An **admin**
   can then open **Incidents -> Review** to play the clip.

Both staff and admins can start/stop their own detection session. Staff can view
incident details, but **only admins can play incident videos**, edit incidents or
change detector settings. One session runs per backend at a time.

**To stop:** stop detection in the dashboard, then press **Ctrl+C** in the terminal.

### Running it again

From SAFE on `main`, pull updates, activate your environment, and start:

```sh
git pull --ff-only origin main
source .venv/bin/activate
python scripts/run_demo.py --service-account "/full/path/to/your-key.json" --record
```

On Windows, replace the activation line with `.\.venv\Scripts\Activate.ps1`.
If dependency files changed after pulling, repeat the two install commands from step 3.

## Recordings: what to expect

- **Red events:** a clip is saved only when `--record` and the dashboard checkbox
  are both enabled. **Amber/yellow events:** event details only, no clip.
- Event details are shared through Firebase. Videos stay on the recording laptop,
  normally in `~/.safe/recordings`, not Firebase Storage.
- Another laptop cannot play your local clips. Old events do not gain clips
  retroactively. Clips expire after 24 hours and may be removed earlier to free space.
- Saved clips are redacted; the live preview is not. Unclear poses may produce
  blacked-out frames. Check saved footage: redaction is not guaranteed anonymity.
- Use consenting teammates and safe staged material. Do not perform real falls.

## Common fixes

| Problem | What to do |
| --- | --- |
| Missing Firebase configuration | Fill in `front-end/.env`, then restart the demo. |
| JSON file not found | Check the full path in `--service-account`, including `.json`. |
| Login/access denied | Ask the project admin to check your active staff profile in `safe-ddacb`. |
| Camera works but no detection | Click **Start detection** and keep the backend terminal open. |
| Staff cannot start detection | Pull the latest `main`, restart both services, and check staff approval. |
| No fall alert | Check full-body pose in **Detection frames**. Detection is imperfect; "falling" is not yet a confirmed red alert. |
| No recording | Check both recording switches, that the event was red, and that you are using the recording laptop. |

To check local setup without starting the servers, add `--check` to the launch command.

## More details

- [Camera setup and detection limitations](BROWSER_CAMERA.md)
- [Recording, privacy and playback](RECORDED_VIDEO.md)
- [Vercel deployment](DEPLOYMENT.md)

<details>
<summary>Run the automated tests</summary>

With your virtual environment activated:

```sh
python -B -m unittest discover -s tests -v
npm test --prefix front-end
```

Tests use mocked Firebase services. They do not prove real-camera accuracy or
privacy. Windows hardware and a fresh Python 3.11 installation still need a device
check; previous local integration checks used an existing macOS Python environment.

</details>

## Team

Advita, Zoe, Shadrach, Phuc, and Filbert.
