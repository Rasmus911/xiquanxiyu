package com.xiquan.mobileordering;

import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import androidx.core.content.FileProvider;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URL;
import java.security.MessageDigest;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

@CapacitorPlugin(name = "ApkUpdater")
public class ApkUpdaterPlugin extends Plugin {
    private static final int BUFFER_SIZE = 64 * 1024;
    private static final long PROGRESS_INTERVAL_MS = 250L;
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final AtomicBoolean downloading = new AtomicBoolean(false);

    @PluginMethod
    public void download(PluginCall call) {
        String urlValue = call.getString("url");
        String expectedSha256 = call.getString("sha256");
        String fileName = call.getString("fileName", "xiquan-update.apk");
        if (!isValidHttpsUrl(urlValue)) {
            call.reject("安装包地址必须使用 HTTPS");
            return;
        }
        if (expectedSha256 == null || !expectedSha256.matches("^[0-9a-f]{64}$")) {
            call.reject("安装包 SHA256 无效");
            return;
        }
        if (fileName == null || !fileName.matches("^[A-Za-z0-9._-]+\\.apk$")) {
            call.reject("安装包文件名无效");
            return;
        }
        if (!downloading.compareAndSet(false, true)) {
            call.reject("已有安装包正在下载");
            return;
        }

        final String safeUrl = urlValue;
        final String safeHash = expectedSha256;
        final String safeFileName = fileName;
        executor.execute(() -> runDownload(call, safeUrl, safeHash, safeFileName));
    }

    private void runDownload(PluginCall call, String urlValue, String expectedSha256, String fileName) {
        File partial = null;
        HttpURLConnection connection = null;
        try {
            File directory = updateDirectory();
            if (!directory.exists() && !directory.mkdirs()) throw new IOException("无法创建更新缓存目录");
            File destination = safeUpdateFile(fileName);
            partial = safeUpdateFile(fileName + ".part");
            if (partial.exists() && !partial.delete()) throw new IOException("无法清理上次未完成的下载");

            connection = openHttpsConnection(new URL(urlValue));
            long totalBytes = connection.getContentLengthLong();
            long downloadedBytes = 0L;
            long lastProgressAt = 0L;
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] buffer = new byte[BUFFER_SIZE];

            try (
                BufferedInputStream input = new BufferedInputStream(connection.getInputStream());
                BufferedOutputStream output = new BufferedOutputStream(new FileOutputStream(partial))
            ) {
                int read;
                while ((read = input.read(buffer)) != -1) {
                    if (Thread.currentThread().isInterrupted()) throw new IOException("下载已取消");
                    output.write(buffer, 0, read);
                    digest.update(buffer, 0, read);
                    downloadedBytes += read;
                    long now = System.currentTimeMillis();
                    if (now - lastProgressAt >= PROGRESS_INTERVAL_MS) {
                        emitProgress(downloadedBytes, totalBytes);
                        lastProgressAt = now;
                    }
                }
            }

            String actualSha256 = ApkUpdateVerifier.toHex(digest.digest());
            if (!actualSha256.equals(expectedSha256)) throw new IOException("HASH_MISMATCH");
            if (destination.exists() && !destination.delete()) throw new IOException("无法替换旧安装包");
            if (!partial.renameTo(destination)) throw new IOException("无法保存已下载的安装包");
            emitProgress(downloadedBytes, downloadedBytes);
            JSObject result = new JSObject();
            result.put("path", destination.getAbsolutePath());
            call.resolve(result);
        } catch (Exception exception) {
            if (partial != null && partial.exists()) partial.delete();
            String message = "HASH_MISMATCH".equals(exception.getMessage())
                ? "HASH_MISMATCH"
                : "安装包下载失败：" + (exception.getMessage() == null ? "未知错误" : exception.getMessage());
            call.reject(message, exception);
        } finally {
            if (connection != null) connection.disconnect();
            downloading.set(false);
        }
    }

    @PluginMethod
    public void canInstallPackages(PluginCall call) {
        JSObject result = new JSObject();
        boolean allowed = Build.VERSION.SDK_INT < Build.VERSION_CODES.O || getContext().getPackageManager().canRequestPackageInstalls();
        result.put("allowed", allowed);
        call.resolve(result);
    }

    @PluginMethod
    public void openInstallSettings(PluginCall call) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Intent intent = new Intent(
                Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                Uri.parse("package:" + getContext().getPackageName())
            );
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(intent);
        }
        call.resolve();
    }

    @PluginMethod
    public void install(PluginCall call) {
        String path = call.getString("path");
        if (path == null) {
            call.reject("缺少安装包路径");
            return;
        }
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && !getContext().getPackageManager().canRequestPackageInstalls()) {
                call.reject("INSTALL_PERMISSION_REQUIRED");
                return;
            }
            File apk = safeExistingUpdateFile(path);
            Uri uri = FileProvider.getUriForFile(
                getContext(),
                getContext().getPackageName() + ".fileprovider",
                apk
            );
            Intent intent = new Intent(Intent.ACTION_VIEW);
            intent.setDataAndType(uri, "application/vnd.android.package-archive");
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(intent);
            call.resolve();
        } catch (Exception exception) {
            call.reject("无法打开系统安装器：" + exception.getMessage(), exception);
        }
    }

    @PluginMethod
    public void clearDownload(PluginCall call) {
        String path = call.getString("path");
        try {
            if (path != null && !path.trim().isEmpty()) {
                File file = safeExistingUpdateFile(path);
                if (!file.delete()) throw new IOException("无法删除安装包");
            } else {
                File[] files = updateDirectory().listFiles();
                if (files != null) {
                    for (File file : files) {
                        if (file.isFile() && (file.getName().endsWith(".apk") || file.getName().endsWith(".part"))) file.delete();
                    }
                }
            }
            call.resolve();
        } catch (Exception exception) {
            call.reject("清理安装包失败：" + exception.getMessage(), exception);
        }
    }

    private void emitProgress(long bytesDownloaded, long totalBytes) {
        int percent = totalBytes > 0 ? (int) Math.min(100L, (bytesDownloaded * 100L) / totalBytes) : 0;
        JSObject event = new JSObject();
        event.put("percent", percent);
        event.put("bytesDownloaded", bytesDownloaded);
        event.put("totalBytes", totalBytes);
        getActivity().runOnUiThread(() -> notifyListeners("downloadProgress", event));
    }

    private HttpURLConnection openHttpsConnection(URL initialUrl) throws IOException {
        URL current = initialUrl;
        for (int redirects = 0; redirects <= 5; redirects++) {
            if (!"https".equalsIgnoreCase(current.getProtocol())) throw new IOException("下载地址必须使用 HTTPS");
            HttpURLConnection connection = (HttpURLConnection) current.openConnection();
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(15_000);
            connection.setReadTimeout(30_000);
            connection.setRequestProperty("Accept", "application/vnd.android.package-archive,application/octet-stream");
            connection.setRequestProperty("User-Agent", "Xiquan-Mobile-Updater");
            int status = connection.getResponseCode();
            if (status >= 200 && status < 300) return connection;
            if (status >= 300 && status < 400) {
                String location = connection.getHeaderField("Location");
                connection.disconnect();
                if (location == null) throw new IOException("服务器重定向缺少地址");
                current = new URL(current, location);
                continue;
            }
            connection.disconnect();
            throw new IOException("服务器返回 HTTP " + status);
        }
        throw new IOException("安装包重定向次数过多");
    }

    private boolean isValidHttpsUrl(String value) {
        try {
            return value != null && "https".equalsIgnoreCase(new URL(value).getProtocol());
        } catch (Exception ignored) {
            return false;
        }
    }

    private File updateDirectory() throws IOException {
        File cache = getContext().getExternalCacheDir();
        if (cache == null) cache = getContext().getCacheDir();
        return new File(cache, "updates").getCanonicalFile();
    }

    private File safeUpdateFile(String fileName) throws IOException {
        File root = updateDirectory();
        File file = new File(root, fileName).getCanonicalFile();
        if (!file.getPath().startsWith(root.getPath() + File.separator)) throw new IOException("安装包路径无效");
        return file;
    }

    private File safeExistingUpdateFile(String path) throws IOException {
        File root = updateDirectory();
        File file = new File(path).getCanonicalFile();
        if (!file.getPath().startsWith(root.getPath() + File.separator) || !file.getName().endsWith(".apk")) {
            throw new IOException("安装包不在应用更新目录中");
        }
        if (!file.isFile()) throw new IOException("安装包不存在");
        return file;
    }

    @Override
    protected void handleOnDestroy() {
        executor.shutdownNow();
        super.handleOnDestroy();
    }
}
