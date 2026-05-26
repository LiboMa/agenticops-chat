# -----------------------------------------------------------------------------
# CloudFront Distribution
# -----------------------------------------------------------------------------

resource "aws_cloudfront_distribution" "app" {
  enabled             = true
  comment             = "${var.project_name} - Singapore deployment"
  default_root_object = ""
  price_class         = "PriceClass_200" # US, Europe, Asia

  origin {
    domain_name = aws_lb.app.dns_name
    origin_id   = "alb"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "alb"
    viewer_protocol_policy = "redirect-to-https"

    # Don't cache API responses — pass everything through
    cache_policy_id          = aws_cloudfront_cache_policy.no_cache.id
    origin_request_policy_id = aws_cloudfront_origin_request_policy.forward_all.id
  }

  # Cache static assets (frontend build)
  ordered_cache_behavior {
    path_pattern           = "/app/assets/*"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "alb"
    viewer_protocol_policy = "redirect-to-https"

    cache_policy_id = aws_cloudfront_cache_policy.static_assets.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  aliases = [var.domain_name]

  viewer_certificate {
    acm_certificate_arn      = var.acm_certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  tags = local.tags
}

# -----------------------------------------------------------------------------
# Cache Policies
# -----------------------------------------------------------------------------

resource "aws_cloudfront_cache_policy" "no_cache" {
  name        = "${var.project_name}-no-cache"
  comment     = "No caching — pass all requests to origin"
  default_ttl = 0
  max_ttl     = 0
  min_ttl     = 0

  parameters_in_cache_key_and_forwarded_to_origin {
    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "none"
    }
  }
}

resource "aws_cloudfront_cache_policy" "static_assets" {
  name        = "${var.project_name}-static-assets"
  comment     = "Cache static frontend assets"
  default_ttl = 86400
  max_ttl     = 604800
  min_ttl     = 0

  parameters_in_cache_key_and_forwarded_to_origin {
    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "none"
    }
  }
}

# -----------------------------------------------------------------------------
# Origin Request Policy — forward headers needed by the app
# -----------------------------------------------------------------------------

resource "aws_cloudfront_origin_request_policy" "forward_all" {
  name    = "${var.project_name}-forward-all"
  comment = "Forward all query strings and relevant headers"

  cookies_config {
    cookie_behavior = "all"
  }

  headers_config {
    header_behavior = "whitelist"
    headers {
      items = [
        "Host",
        "Origin",
        "Referer",
        "Authorization",
        "Content-Type",
        "Accept",
      ]
    }
  }

  query_strings_config {
    query_string_behavior = "all"
  }
}
