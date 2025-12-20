# Diagrams

The diagrams below are generated on release builds. If you do not see the images, grab them from:\n\n- Release assets: https://github.com/miciav/linux-benchmark-lib/releases\n- Workflow artifacts: https://github.com/miciav/linux-benchmark-lib/actions/workflows/diagrams.yml

## Class diagram

![Class diagram](diagrams/classes.png)

## Package diagram

![Package diagram](diagrams/packages.png)

## How to regenerate

```bash
pip install "pylint==3.3.1"
mkdir -p docs/diagrams
pyreverse -o png -p linux-benchmark lb_runner lb_controller lb_app lb_ui lb_analytics -S
mv classes*.png docs/diagrams/classes.png
mv packages*.png docs/diagrams/packages.png
pyreverse -o puml -p linux-benchmark lb_runner lb_controller lb_app lb_ui lb_analytics -S
mv classes*.puml docs/diagrams/classes.puml
mv packages*.puml docs/diagrams/packages.puml
```
