/* Klien API dan aliran log server lokal (tanpa dependensi). */
(function () {
  "use strict";

  function detailOf(data, fallback) {
    if (!data) return fallback;
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) {
      return data.detail.map(function (item) {
        return item.msg || JSON.stringify(item);
      }).join("; ");
    }
    if (data.detail) return JSON.stringify(data.detail);
    return fallback;
  }

  function request(path, options) {
    options = options || {};
    var init = {
      method: options.method || "GET",
      credentials: "same-origin",
      headers: options.headers || {}
    };
    if (options.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }
    return fetch(path, init).then(function (response) {
      return response.text().then(function (text) {
        var data = null;
        if (text) {
          try {
            data = JSON.parse(text);
          } catch (error) {
            data = { detail: text };
          }
        }
        if (!response.ok) {
          var failure = new Error(detailOf(data, response.statusText));
          failure.status = response.status;
          failure.payload = data;
          throw failure;
        }
        return data;
      });
    });
  }

  function get(path) {
    return request(path);
  }

  function put(path, body) {
    return request(path, { method: "PUT", body: body === undefined ? {} : body });
  }

  function post(path, body) {
    return request(path, { method: "POST", body: body === undefined ? {} : body });
  }

  function streamJob(jobId, handlers, startIndex) {
    handlers = handlers || {};
    var index = Math.max(0, Number(startIndex) || 0);
    var finished = false;
    var source = new EventSource(
      "/api/jobs/" + encodeURIComponent(jobId) + "/stream?index=" + index
    );

    source.addEventListener("log", function (event) {
      var data = {};
      try {
        data = JSON.parse(event.data);
      } catch (error) {
        return;
      }
      index = Number(data.index || index) + 1;
      if (handlers.onLog) handlers.onLog(data.line, data.index);
    });
    source.addEventListener("state", function (event) {
      var data = {};
      try {
        data = JSON.parse(event.data);
      } catch (error) {
        return;
      }
      if (handlers.onState) handlers.onState(data);
    });
    source.addEventListener("end", function (event) {
      finished = true;
      source.close();
      var data = {};
      try {
        data = JSON.parse(event.data);
      } catch (error) {
        data = {};
      }
      if (handlers.onEnd) handlers.onEnd(data);
    });
    source.onerror = function () {
      if (finished) return;
      source.close();
      if (handlers.onError) handlers.onError(new Error("Koneksi log terputus."));
    };

    return {
      close: function () {
        finished = true;
        source.close();
      }
    };
  }

  window.BIToolsApi = {
    get: get,
    put: put,
    post: post,
    streamJob: streamJob
  };
})();
