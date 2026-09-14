# Push this folder to GitHub

This folder is an independent Git repository on the `main` branch. No commit or GitHub remote has been created yet.

1. On GitHub, create a new repository named `solar-blender`, or choose your own name and visibility. Leave **Add a README file**, **Add .gitignore** and **Choose a license** unselected so the remote starts empty.
2. Open PowerShell in this `solar_blender` folder. Stage the files, inspect the selection and create the first commit:

   ```powershell
   git add .
   git status
   git commit -m "Initial Blender Sun visualization"
   ```

3. Replace `YOUR_USERNAME` and, if necessary, the repository name below. Connect the remote and push:

   ```powershell
   git remote add origin https://github.com/YOUR_USERNAME/solar-blender.git
   git push -u origin main
   ```

   Complete GitHub authentication if Git prompts for it. Refresh the repository page to see the README, preview images, source code and editable Blender scene.

The included `.gitignore` keeps full-resolution renders, caches, virtual environments and Blender backups out of the repository. The `.blend`, compact previews and prepared input assets are intentionally tracked. The current files fit GitHub's normal file limits; Git LFS is not required for this package.

If Git asks for your identity before the first commit, configure it for this repository and retry the commit:

```powershell
git config user.name "Your Name"
git config user.email "YOUR_COMMIT_EMAIL"
git commit -m "Initial Blender Sun visualization"
```

Use an email associated with your GitHub account, or your GitHub-provided private commit email. These commands set repository-local values.

To publish later changes:

```powershell
git add .
git status
git commit -m "Update solar visualization"
git push
```

No license has been selected for you. Choose an appropriate code license if you want to grant reuse rights, while retaining the data-source attribution in `assets/`.

GitHub's official instructions cover [adding locally hosted code](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github) and [large-file limits](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github).
