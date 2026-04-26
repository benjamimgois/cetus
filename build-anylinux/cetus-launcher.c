#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <libgen.h>

int main(int argc, char *argv[])
{
    char self[PATH_MAX];
    ssize_t len = readlink("/proc/self/exe", self, PATH_MAX - 1);
    if (len < 0) { perror("readlink /proc/self/exe"); return 1; }
    self[len] = '\0';

    /* shared/bin/cetus  →  dirname x2  →  AppDir root  */
    char *p1 = strdup(self);
    char *bin_dir    = strdup(dirname(p1));      /* …/shared/bin   */
    char *shared_dir = strdup(dirname(bin_dir)); /* …/shared       */
    char *app_dir    = strdup(dirname(shared_dir)); /* AppDir root */
    free(p1);

    char python[PATH_MAX], script[PATH_MAX];
    snprintf(python, PATH_MAX, "%s/bin/python3",               app_dir);
    snprintf(script, PATH_MAX, "%s/usr/share/cetus/cetus", app_dir);
    free(bin_dir); free(shared_dir); free(app_dir);

    char **new_argv = malloc((argc + 2) * sizeof(char *));
    if (!new_argv) return 1;
    new_argv[0] = python;
    new_argv[1] = script;
    for (int i = 1; i < argc; i++) new_argv[i + 1] = argv[i];
    new_argv[argc + 1] = NULL;

    /* Try bundled python3; fall back to PATH if not accessible. */
    if (access(python, X_OK) == 0) {
        execv(python, new_argv);
    }
    /* Fallback: shift new_argv to skip python path, use execvp */
    new_argv[0] = "python3";
    execvp("python3", new_argv);
    perror("execvp python3");
    return 1;
}
