<?php
/**
 * API de génération PDF pour le viewer (WAMP / Apache + PHP).
 */

declare(strict_types=1);

header('X-Content-Type-Options: nosniff');

$viewerDir = __DIR__;
$projectDir = dirname($viewerDir);
$manualSlug = preg_replace('/[^a-z0-9_-]/', '', strtolower((string) ($_GET['manual'] ?? 'elroq')));
if ($manualSlug === '') {
    $manualSlug = 'elroq';
}

$manualDir = $projectDir . DIRECTORY_SEPARATOR . 'manuals' . DIRECTORY_SEPARATOR . $manualSlug;
$statusFile = $manualDir . DIRECTORY_SEPARATOR . 'pdf_build_status.json';
$pdfFile = $manualDir . DIRECTORY_SEPARATOR . 'manual.pdf';
$lockFile = $manualDir . DIRECTORY_SEPARATOR . 'pdf_build.lock';
$logFile = $manualDir . DIRECTORY_SEPARATOR . 'pdf_build.log';
$envBat = $projectDir . DIRECTORY_SEPARATOR . 'pdf_env.bat';
$script = $projectDir . DIRECTORY_SEPARATOR . 'build_manual_pdf.py';
$runner = $projectDir . DIRECTORY_SEPARATOR . 'run_pdf_build.bat';

$action = $_GET['action'] ?? 'status';

function read_status(string $path): array
{
    if (!is_file($path)) {
        return ['state' => 'idle'];
    }
    $raw = file_get_contents($path);
    if ($raw === false || trim($raw) === '') {
        return ['state' => 'idle'];
    }
    $data = json_decode($raw, true);
    return is_array($data) ? $data : ['state' => 'idle'];
}

function json_response(array $payload, int $code = 200): void
{
    http_response_code($code);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($payload, JSON_UNESCAPED_UNICODE);
    exit;
}

function log_tail_since_last_run(string $logFile): string
{
    if (!is_file($logFile)) {
        return '';
    }
    $content = (string) file_get_contents($logFile);
    $pos = strrpos($content, '====');
    if ($pos === false) {
        return $content;
    }
    return substr($content, $pos);
}

function log_tail_has_error(string $logFile): ?string
{
    $tail = log_tail_since_last_run($logFile);
    if ($tail === '') {
        return null;
    }
    if (str_contains($tail, 'Aucun Python avec Playwright')) {
        return 'Python Playwright introuvable pour Apache. Lancez : python setup_local_env.py';
    }
    if (preg_match('/ModuleNotFoundError[^\r\n]*/', $tail, $m)) {
        return trim($m[0]) . ' — lancez : pip install playwright';
    }
    if (preg_match('/Erreur PDF\s*:\s*([^\r\n]+)/', $tail, $m)) {
        return trim($m[1]);
    }
    if (str_contains($tail, 'Traceback (most recent call last)')) {
        if (preg_match('/\n([A-Za-z_][\w.]*Error[^\r\n]*)\s*$/', $tail, $m)) {
            return trim($m[1]);
        }
        return 'Erreur Python (voir pdf_build.log)';
    }
    return null;
}

function enrich_status(array $status, string $statusFile, string $lockFile, string $logFile, string $pdfFile, string $manualSlug = 'elroq'): array
{
    $updatedAt = $status['updatedAt'] ?? null;
    $ageSec = 0;
    if (is_string($updatedAt)) {
        $ts = strtotime($updatedAt);
        if ($ts !== false) {
            $ageSec = time() - $ts;
        }
    }

    if (($status['state'] ?? '') === 'building') {
        $phase = $status['phase'] ?? '';
        if ($ageSec > 15 && ($phase === 'start' || ($status['total'] ?? 0) === 0)) {
            $logError = log_tail_has_error($logFile);
            if ($logError !== null) {
                $status['state'] = 'error';
                $status['message'] = $logError;
                @file_put_contents($statusFile, json_encode($status, JSON_UNESCAPED_UNICODE));
                if (is_file($lockFile)) {
                    @unlink($lockFile);
                }
            } elseif ($ageSec > 30 && !str_contains(log_tail_since_last_run($logFile), 'manual=')) {
                $status['state'] = 'error';
                $status['message'] = 'Le processus PDF n\'a pas démarré (permissions Apache ?). Lancez : python build_manual_pdf.py --manual ' . $manualSlug;
                @file_put_contents($statusFile, json_encode($status, JSON_UNESCAPED_UNICODE));
                if (is_file($lockFile)) {
                    @unlink($lockFile);
                }
            }
        }
    }

    if (($status['state'] ?? '') === 'done' && is_file($pdfFile)) {
        $status['pdfReady'] = true;
        $status['pdfSizeMb'] = round(filesize($pdfFile) / (1024 * 1024), 2);
    }

    return $status;
}

function launch_pdf_build(string $projectDir, string $logFile, string $runner, string $manualSlug): bool
{
    if (!is_file($runner)) {
        return false;
    }

    $targetFile = $projectDir . DIRECTORY_SEPARATOR . 'pdf_build_target.txt';
    if (@file_put_contents($targetFile, $manualSlug . "\n") === false) {
        return false;
    }

    $stamp = gmdate('Y-m-d H:i:s') . ' UTC';
    @file_put_contents($logFile, "==== {$stamp} ====\n", FILE_APPEND);
    @file_put_contents($logFile, "PHP lance : {$runner} (manual={$manualSlug})\n", FILE_APPEND);

    if (strtoupper(substr(PHP_OS, 0, 3)) === 'WIN') {
        // start /B n'accepte qu'une commande : ne pas passer le slug en 3e argument.
        $cmd = 'cmd /C start /B "" /D '
            . escapeshellarg($projectDir) . ' '
            . escapeshellarg($runner);
        pclose(popen($cmd, 'r'));
        return true;
    }

    $cmd = 'cd ' . escapeshellarg($projectDir) . ' && '
        . escapeshellarg($runner) . ' > /dev/null 2>&1 &';
    pclose(popen($cmd, 'r'));
    return true;
}

if (!is_dir($manualDir)) {
    json_response(['ok' => false, 'error' => "Manuel introuvable : {$manualSlug}"], 404);
}

switch ($action) {
    case 'start':
        if (!is_file($envBat)) {
            json_response([
                'ok' => false,
                'error' => 'Configuration PDF absente. Lancez : python setup_local_env.py',
            ], 500);
        }

        if (!is_file($runner)) {
            json_response(['ok' => false, 'error' => 'run_pdf_build.bat introuvable.'], 500);
        }

        $status = enrich_status(read_status($statusFile), $statusFile, $lockFile, $logFile, $pdfFile, $manualSlug);
        if (($status['state'] ?? '') === 'building') {
            json_response(['ok' => true, 'alreadyRunning' => true, 'status' => $status]);
        }

        if (is_file($lockFile)) {
            $age = time() - (int) @filemtime($lockFile);
            if ($age < 7200) {
                json_response(['ok' => true, 'alreadyRunning' => true, 'status' => $status]);
            }
        }

        @file_put_contents($lockFile, (string) time());
        @file_put_contents($statusFile, json_encode([
            'state' => 'building',
            'phase' => 'start',
            'progress' => 0,
            'total' => 0,
            'message' => 'Démarrage du moteur PDF…',
            'updatedAt' => gmdate('c'),
        ], JSON_UNESCAPED_UNICODE));

        if (!launch_pdf_build($projectDir, $logFile, $runner, $manualSlug)) {
            json_response(['ok' => false, 'error' => 'run_pdf_build.bat introuvable.'], 500);
        }

        json_response(['ok' => true, 'started' => true, 'manual' => $manualSlug]);

    case 'status':
        $status = enrich_status(read_status($statusFile), $statusFile, $lockFile, $logFile, $pdfFile, $manualSlug);
        if (($status['state'] ?? '') !== 'building' && is_file($lockFile)) {
            @unlink($lockFile);
        }
        json_response(['ok' => true, 'status' => $status, 'manual' => $manualSlug]);

    case 'download':
        if (!is_file($pdfFile)) {
            json_response(['ok' => false, 'error' => 'PDF non généré.'], 404);
        }
        header('Content-Type: application/pdf');
        header('Content-Disposition: attachment; filename="manuel_skoda_' . $manualSlug . '.pdf"');
        header('Content-Length: ' . (string) filesize($pdfFile));
        readfile($pdfFile);
        exit;

    default:
        json_response(['ok' => false, 'error' => 'Action inconnue.'], 400);
}
