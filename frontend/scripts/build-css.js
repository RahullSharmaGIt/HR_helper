const fs = require('fs');
const path = require('path');
const postcss = require('postcss');
const tailwind = require('@tailwindcss/postcss');

const rootDir = path.resolve(__dirname, '..');
const inputFile = path.join(rootDir, 'src', 'app', 'globals.source.css');
const outputFile = path.join(rootDir, 'src', 'app', 'globals.css');

if (!fs.existsSync(inputFile)) {
  const currentContent = fs.readFileSync(outputFile, 'utf8');
  fs.writeFileSync(inputFile, currentContent, 'utf8');
}

const inputCss = fs.readFileSync(inputFile, 'utf8');

postcss([tailwind()])
  .process(inputCss, { from: inputFile, to: outputFile })
  .then((result) => {
    fs.writeFileSync(outputFile, result.css, 'utf8');
    console.log(`Successfully compiled Tailwind CSS to ${outputFile} (${(result.css.length / 1024).toFixed(1)} KB)`);
  })
  .catch((err) => {
    console.error('Error compiling Tailwind CSS:', err);
    process.exit(1);
  });
