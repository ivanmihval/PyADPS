import click
import os
import os.path


@click.group()
def cli():
    pass


@cli.command()
@click.argument('repo_folder', type=click.Path(exists=True, file_okay=False))
def init(repo_folder):
    os.mkdir(os.path.join(repo_folder, 'adps_messages'))
    os.mkdir(os.path.join(repo_folder, 'adps_attachments'))


if __name__ == '__main__':
    cli()
