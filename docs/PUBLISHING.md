# Publish the prepared repository

The prepared local checkout uses the `main` branch. No remote repository or
release is created by preparing the files.

## GitHub repository

From this directory, inspect the README, license and tracked files. If you
downloaded the source ZIP, initialize it first:

```bash
git init -b main
git add .
git commit -m "Initial knight versus bishop study"
```

With GitHub CLI installed and authenticated, create your repository. Choose
`--public` or `--private` for its visibility; this example publishes publicly:

```bash
gh repo create knight-vs-bishop --public --source . --remote origin --push
```

Alternatively, create an empty repository on GitHub, copy its remote URL, run
`git remote add origin YOUR_REPOSITORY_URL`, then `git push -u origin main`.
`YOUR_REPOSITORY_URL` is a placeholder for your own repository URL.

## Optional graph website

In the repository's **Settings → Pages**, select **GitHub Actions** as the source.
Then run **Publish graph gallery** from the Actions tab. The manually triggered
workflow deploys only `results/`, after checking the report. It does not run on
every push and does not download games or publish reduced databases. Hosting
availability depends on your repository visibility and GitHub account settings.

`results/index.html` is the landing page. The gallery and main report embed
their figures and need no external chart service. Relative links to Markdown
documentation are rewritten to GitHub in the Pages artifact.

## Optional reduced-data release

The large reduced-data ZIP stays outside the repository. Attach it to a release
after publishing; for example:

```bash
gh release create v0.1.0 /path/to/knight_bishop_reduced_data.zip --title "Published study and reduced data" --notes-file CHANGELOG.md
```

The archive manifest in `docs/data_assets.json` lets consumers verify it. Add
the release download link to `docs/DATA.md` once that release exists.
[GitHub's large-file guidance](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)
explains the normal Git limits and release-asset alternative.
