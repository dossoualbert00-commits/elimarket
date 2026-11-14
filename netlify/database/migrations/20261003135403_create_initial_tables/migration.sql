CREATE TABLE "admin_users" (
	"id" serial PRIMARY KEY,
	"username" text NOT NULL UNIQUE,
	"password_hash" text NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "categories" (
	"id" text PRIMARY KEY,
	"name" text NOT NULL,
	"description" text NOT NULL,
	"icon_name" text NOT NULL,
	"image" text NOT NULL,
	"product_count" integer DEFAULT 0
);
--> statement-breakpoint
CREATE TABLE "order_requests" (
	"id" serial PRIMARY KEY,
	"type" text NOT NULL,
	"customer_name" text NOT NULL,
	"customer_phone" text NOT NULL,
	"customer_email" text,
	"country" text NOT NULL,
	"city" text NOT NULL,
	"status" text DEFAULT 'nouveau' NOT NULL,
	"details" json NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "products" (
	"id" serial PRIMARY KEY,
	"slug" text NOT NULL UNIQUE,
	"name" text NOT NULL,
	"category" text NOT NULL,
	"category_name" text NOT NULL,
	"price" integer NOT NULL,
	"original_price" integer,
	"is_quote_only" boolean DEFAULT false,
	"description" text NOT NULL,
	"short_description" text NOT NULL,
	"images" text[] NOT NULL,
	"featured" boolean DEFAULT false,
	"in_stock" boolean DEFAULT true,
	"badge" text,
	"rating" numeric(2,1) DEFAULT '4.8',
	"reviews_count" integer DEFAULT 12,
	"variants" json DEFAULT '[]',
	"features" text[] DEFAULT '{}'::text[],
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL
);
